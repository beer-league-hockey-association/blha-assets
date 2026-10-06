"""Discord layer for the BLHA Voting Bot (discord.py 2.x).

Slash commands:
  /proposal new        post a written amendment proposal (20.2)
  /vote open           Commissioner opens voting on a proposal (20.3)
  /vote removal        any Franchise Owner starts a removal vote (19.5)
  /vote elect          any Franchise Owner starts an Interim or permanent
                       Commissioner election (19.4)
  /vote status         who has voted so far (not how)
  /vote cancel         Commissioner withdraws an amendment vote
  /franchise orphan    Commissioner marks a franchise orphaned (2.3)
  /panel draw          Commissioner or an Assistant draws a Review Panel (19.4)

Ballots are buttons on the vote post. They are private, can be changed until
the vote closes, and close automatically after the window.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from discord.ext import tasks

from . import embeds, rules
from .config import BotConfig
from .store import Store, parse

log = logging.getLogger("blha.vote")

# Fantrax helpers shared with the GitHub automation (automation/blha).
AUTOMATION = Path(__file__).resolve().parents[2] / "automation"
if str(AUTOMATION) not in sys.path:
    sys.path.insert(0, str(AUTOMATION))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def fantrax_phase() -> tuple[str | None, datetime | None]:
    """(phase, start of Week 1 if it is still ahead) from Fantrax; (None, None) on failure."""
    try:
        from blha import season
        from blha.fantrax import Fantrax
        from blha.league import load_league

        info = Fantrax(str(load_league()["league_id"]), user_agent="BLHA-VoteBot/1.0").league_info()
        now = utcnow()
        phase = season.phase(info, now)
        weeks = season.periods(info)
        start = weeks[0].start if weeks and phase == season.PRESEASON else None
        return phase, start
    except Exception as exc:  # network or Fantrax error: fail closed
        log.warning("Fantrax phase check failed: %s", exc)
        return None, None


def as_dict(row: Any) -> dict[str, Any]:
    d = dict(row)
    for key in ("closes_at", "opened_at", "posted_at"):
        if isinstance(d.get(key), str):
            d[key] = parse(d[key])
    return d


class VoteView(discord.ui.View):
    """Persistent ballot buttons (or a candidate menu) for one vote."""

    def __init__(self, bot: "VoteBot", vote: dict[str, Any]) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.vote_id = int(vote["id"])
        kind = rules.KINDS[vote["kind"]]
        if kind.rule == "supermajority":
            for choice, style in ((rules.YES, discord.ButtonStyle.success),
                                  (rules.NO, discord.ButtonStyle.danger),
                                  (rules.ABSTAIN, discord.ButtonStyle.secondary)):
                button = discord.ui.Button(label=embeds.CHOICE_LABEL[choice], style=style,
                                           custom_id=f"blha:vote:{self.vote_id}:{choice}")
                button.callback = self._make_callback(choice)
                self.add_item(button)
        else:
            import json
            options = json.loads(vote["options"]) if isinstance(vote["options"], str) else vote["options"]
            select = discord.ui.Select(
                placeholder="Choose a candidate",
                custom_id=f"blha:vote:{self.vote_id}:select",
                options=[discord.SelectOption(label=o[:100], value=o[:100]) for o in options]
                + [discord.SelectOption(label="Abstain", value=rules.ABSTAIN)],
            )

            async def picked(interaction: discord.Interaction) -> None:
                await self.bot.record_ballot(interaction, self.vote_id, select.values[0])

            select.callback = picked
            self.add_item(select)

    def _make_callback(self, choice: str):
        async def callback(interaction: discord.Interaction) -> None:
            await self.bot.record_ballot(interaction, self.vote_id, choice)
        return callback


class ProposalModal(discord.ui.Modal, title="Amendment proposal"):
    prop_title = discord.ui.TextInput(label="Title", max_length=100)
    affected = discord.ui.TextInput(label="Affected rule (Article and Section)", max_length=200)
    replacement = discord.ui.TextInput(label="Exact replacement language", style=discord.TextStyle.paragraph,
                                       max_length=1000)
    season = discord.ui.TextInput(label="Season it takes effect (e.g. 2029)", max_length=4, min_length=4)

    def __init__(self, bot: "VoteBot", kind: str, proposed_by: str) -> None:
        super().__init__()
        self.bot, self.kind, self.proposed_by = bot, kind, proposed_by

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not str(self.season.value).isdigit():
            await interaction.response.send_message("The Season must be a year, like 2029.", ephemeral=True)
            return
        await self.bot.post_proposal(interaction, self.kind, str(self.prop_title.value), str(self.affected.value),
                                     str(self.replacement.value), int(str(self.season.value)), self.proposed_by)


class VoteBot(discord.Client):
    def __init__(self, cfg: BotConfig, store: Store) -> None:
        intents = discord.Intents.default()
        intents.members = True  # Review Panel draws read role members
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.cfg = cfg
        self.store = store
        self.tree = app_commands.CommandTree(self)
        self.rng = random.SystemRandom()
        self._build_commands()

    # -- helpers -----------------------------------------------------------
    def franchises(self) -> list[rules.Franchise]:
        orphaned = self.store.orphaned()
        return [rules.Franchise(f.name, f.role_id, f.commissioner, f.name in orphaned) for f in self.cfg.franchises]

    @staticmethod
    def role_ids(member: Any) -> set[int]:
        return {r.id for r in getattr(member, "roles", [])}

    def is_commissioner(self, member: Any) -> bool:
        return bool(self.cfg.commissioner_role_id) and self.cfg.commissioner_role_id in self.role_ids(member)

    def is_assistant(self, member: Any) -> bool:
        return bool(self.cfg.assistant_role_id) and self.cfg.assistant_role_id in self.role_ids(member)

    def owner_franchise(self, member: Any) -> rules.Franchise | None:
        any_kind = rules.KINDS["amendment"]
        franchise, _ = rules.can_cast(self.role_ids(member), self.cfg.owner_role_id, self.franchises(), any_kind)
        return franchise

    async def channel(self, channel_id: int | None) -> discord.abc.Messageable | None:
        if not channel_id:
            return None
        return self.get_channel(channel_id) or await self.fetch_channel(channel_id)

    # -- lifecycle ---------------------------------------------------------
    async def setup_hook(self) -> None:
        for vote in self.store.open_votes():
            if vote["message_id"]:
                self.add_view(VoteView(self, as_dict(vote)), message_id=int(vote["message_id"]))
        if self.cfg.guild_id:
            guild = discord.Object(id=self.cfg.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        self.ticker.start()

    async def on_ready(self) -> None:
        log.info("Logged in as %s; %d open votes", self.user, len(self.store.open_votes()))
        for problem in self.cfg.problems:
            log.warning("Config: %s", problem)

    @tasks.loop(minutes=1)
    async def ticker(self) -> None:
        now = utcnow()
        for vote in self.store.due_reminder(now, self.cfg.remind_hours):
            await self.send_reminder(as_dict(vote))
        for vote in self.store.due_to_close(now):
            await self.close_vote(as_dict(vote))

    @ticker.before_loop
    async def _wait(self) -> None:
        await self.wait_until_ready()

    # -- actions -----------------------------------------------------------
    async def post_proposal(self, interaction: discord.Interaction, kind: str, title: str, affected: str,
                            replacement: str, season: int, proposed_by: str) -> None:
        now = utcnow()
        pid = self.store.add_proposal(title=title, affected_rule=affected, replacement=replacement,
                                      effective_season=season, kind=kind, proposed_by=proposed_by,
                                      user_id=interaction.user.id, now=now)
        row = as_dict(self.store.proposal(pid))
        opens = now + timedelta(days=self.cfg.settings.notice_days)
        channel = await self.channel(self.cfg.voting_channel_id)
        msg = await channel.send(embed=discord.Embed.from_dict(embeds.proposal(row, opens)))
        self.store.set_proposal_message(pid, msg.channel.id, msg.id)
        await interaction.response.send_message(f"Proposal #{pid} posted in {msg.jump_url}.", ephemeral=True)

    async def start_vote(self, interaction: discord.Interaction, kind_key: str, title: str, question: str,
                         options: list[str], proposal_id: int | None, effective: str | None,
                         warnings: list[str]) -> None:
        kind = rules.KINDS[kind_key]
        now = utcnow()
        closes = now + timedelta(days=self.cfg.settings.window_days)
        vid = self.store.open_vote(kind=kind_key, title=title, question=question, options=options,
                                   proposal_id=proposal_id, effective=effective, user_id=interaction.user.id,
                                   now=now, closes_at=closes)
        vote = as_dict(self.store.vote(vid))
        threshold = rules.threshold_text(kind, self.cfg.settings, self.franchises())
        embed = discord.Embed.from_dict(embeds.vote_open(vote, kind, threshold, options, warnings))
        channel = await self.channel(self.cfg.voting_channel_id)
        roles = [discord.Object(id=f.role_id) for f in rules.eligible(self.franchises(), kind) if f.role_id > 0]
        mention = " ".join(f"<@&{r.id}>" for r in roles)
        view = VoteView(self, vote)
        msg = await channel.send(content=mention or None, embed=embed, view=view,
                                 allowed_mentions=discord.AllowedMentions(roles=roles))
        self.store.set_vote_message(vid, msg.channel.id, msg.id)
        await interaction.followup.send(f"Vote #{vid} is open: {msg.jump_url}", ephemeral=True)

    async def record_ballot(self, interaction: discord.Interaction, vote_id: int, choice: str) -> None:
        row = self.store.vote(vote_id)
        now = utcnow()
        if row is None or row["status"] != "open" or parse(row["closes_at"]) <= now:
            await interaction.response.send_message("This vote is closed.", ephemeral=True)
            return
        kind = rules.KINDS[row["kind"]]
        franchise, why = rules.can_cast(self.role_ids(interaction.user), self.cfg.owner_role_id,
                                        self.franchises(), kind)
        if franchise is None:
            await interaction.response.send_message(why, ephemeral=True)
            return
        changed = self.store.cast(vote_id, franchise.name, choice, interaction.user.id, now=now)
        label = embeds.CHOICE_LABEL.get(choice, choice)
        verb = "changed to" if changed else "recorded as"
        await interaction.response.send_message(
            f"{franchise.name}'s vote is {verb} **{label}**. You can change it until "
            f"{embeds.stamp(parse(row['closes_at']))}.", ephemeral=True)

    async def send_reminder(self, vote: dict[str, Any]) -> None:
        kind = rules.KINDS[vote["kind"]]
        ballots = self.store.ballots(vote["id"])
        missing = [f for f in rules.eligible(self.franchises(), kind) if f.name not in ballots]
        channel = await self.channel(vote["channel_id"])
        if channel and missing:
            roles = [discord.Object(id=f.role_id) for f in missing if f.role_id > 0]
            await channel.send(content=" ".join(f"<@&{r.id}>" for r in roles) or None,
                               embed=discord.Embed.from_dict(embeds.reminder(vote, [f.name for f in missing])),
                               allowed_mentions=discord.AllowedMentions(roles=roles))
        self.store.mark_reminded(vote["id"])

    async def close_vote(self, vote: dict[str, Any]) -> None:
        import json
        kind = rules.KINDS[vote["kind"]]
        ballots = self.store.ballots(vote["id"])
        options = json.loads(vote["options"]) if isinstance(vote["options"], str) else vote["options"]
        outcome = rules.tally(kind, ballots, self.franchises(), self.cfg.settings, options)
        self.store.close_vote(vote["id"], {"passed": outcome.passed, "winner": outcome.winner,
                                           "counts": outcome.counts, "not_voted": outcome.not_voted},
                              now=utcnow())
        shown = {k: v for k, v in ballots.items() if k in {f.name for f in rules.eligible(self.franchises(), kind)}}
        embed = embeds.result(vote, kind, outcome, shown if self.cfg.publish_ballots else None)
        channel = await self.channel(vote["channel_id"])
        if channel is None:
            return
        await channel.send(embed=discord.Embed.from_dict(embed))
        try:
            original = await channel.fetch_message(int(vote["message_id"]))
            await original.edit(view=None)
        except Exception as exc:
            log.warning("Could not remove ballot buttons on vote %s: %s", vote["id"], exc)

    # -- commands ----------------------------------------------------------
    def _build_commands(self) -> None:
        bot = self
        proposal = app_commands.Group(name="proposal", description="Amendment proposals (Article XX)", guild_only=True)
        vote = app_commands.Group(name="vote", description="League votes", guild_only=True)
        franchise = app_commands.Group(name="franchise", description="Franchise status", guild_only=True)
        panel = app_commands.Group(name="panel", description="Review Panel (19.4)", guild_only=True)

        @proposal.command(name="new", description="Post a written amendment proposal (20.2)")
        @app_commands.describe(kind="Use 'services' only to change the League Services Allocation (3.6)")
        @app_commands.choices(kind=[app_commands.Choice(name="Material Amendment", value="amendment"),
                                    app_commands.Choice(name="League Services Allocation change", value="services")])
        async def proposal_new(interaction: discord.Interaction, kind: app_commands.Choice[str]) -> None:
            if bot.is_commissioner(interaction.user):
                by = "Commissioner"
            else:
                f = bot.owner_franchise(interaction.user)
                if f is None:
                    await interaction.response.send_message(
                        "Only a Franchise Owner or the Commissioner can propose an amendment (20.2).", ephemeral=True)
                    return
                by = f.name
            await interaction.response.send_modal(ProposalModal(bot, kind.value, by))

        @vote.command(name="open", description="Commissioner: open voting on a proposal")
        async def vote_open(interaction: discord.Interaction, proposal_id: int) -> None:
            if not bot.is_commissioner(interaction.user):
                await interaction.response.send_message("Only the Commissioner opens amendment votes.", ephemeral=True)
                return
            row = bot.store.proposal(proposal_id)
            if row is None or row["status"] != "discussion":
                await interaction.response.send_message("No proposal in discussion has that number.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            phase, week1 = await asyncio.to_thread(fantrax_phase)
            kind = rules.KINDS[row["kind"]]
            blocking, warnings = rules.open_problems(
                kind, now=utcnow(), phase=phase, proposal_posted_at=parse(row["posted_at"]),
                effective_season=row["effective_season"], settings=bot.cfg.settings, next_season_start=week1)
            if blocking:
                await interaction.followup.send("Can't open this vote yet:\n- " + "\n- ".join(blocking), ephemeral=True)
                return
            question = f"Adopt this change to {row['affected_rule']}?\n> {row['replacement'][:800]}"
            await bot.start_vote(interaction, row["kind"], row["title"], question, [], proposal_id,
                                 f"Season {row['effective_season']}", warnings)

        @vote.command(name="removal", description="Start a vote to remove the Commissioner for cause (19.5)")
        async def vote_removal(interaction: discord.Interaction, cause: str) -> None:
            kind = rules.KINDS["removal"]
            f, why = rules.can_cast(bot.role_ids(interaction.user), bot.cfg.owner_role_id, bot.franchises(), kind)
            if f is None:
                await interaction.response.send_message(why, ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            question = (f"Remove the Commissioner for cause? Cause stated by {f.name}: {cause[:700]}\n"
                        "Cause means documented misuse of league funds, repeated violation of the Constitution, "
                        "or abandonment of the office (19.5).")
            await bot.start_vote(interaction, "removal", "Commissioner removal", question, [], None, None, [])

        @vote.command(name="elect", description="Elect an Interim or permanent Commissioner (19.4)")
        @app_commands.describe(candidates="Mention each candidate, e.g. @Alex @Sam")
        @app_commands.choices(office=[app_commands.Choice(name="Interim Commissioner", value="interim"),
                                      app_commands.Choice(name="Permanent Commissioner", value="commissioner")])
        async def vote_elect(interaction: discord.Interaction, office: app_commands.Choice[str], candidates: str) -> None:
            if bot.owner_franchise(interaction.user) is None and not bot.is_commissioner(interaction.user):
                await interaction.response.send_message("Only a Franchise Owner can start this vote.", ephemeral=True)
                return
            ids = [int(x) for x in re.findall(r"<@!?(\d+)>", candidates)]
            guild = interaction.guild
            names: list[str] = []
            for uid in dict.fromkeys(ids):
                member = guild.get_member(uid) if guild else None
                label = (member.display_name if member else f"User {uid}")[:90]
                names.append(label if label not in names else f"{label} ({uid})"[:100])
            if not 1 <= len(names) <= 24:
                await interaction.response.send_message("Mention between 1 and 24 candidates.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            question = f"Who should be {office.name}? A majority of active franchises is needed."
            await bot.start_vote(interaction, office.value, office.name, question, names, None, None, [])

        @vote.command(name="status", description="Which franchises have voted (not how)")
        async def vote_status(interaction: discord.Interaction, vote_id: int) -> None:
            row = bot.store.vote(vote_id)
            if row is None:
                await interaction.response.send_message("No vote has that number.", ephemeral=True)
                return
            kind = rules.KINDS[row["kind"]]
            ballots = bot.store.ballots(vote_id)
            eligible = rules.eligible(bot.franchises(), kind)
            done = [f.name for f in eligible if f.name in ballots]
            waiting = [f.name for f in eligible if f.name not in ballots]
            await interaction.response.send_message(
                f"**{row['title']}** ({row['status']}), closes {embeds.stamp(parse(row['closes_at']))}\n"
                f"Voted ({len(done)}): {', '.join(done) or 'none'}\nNot yet ({len(waiting)}): {', '.join(waiting) or 'none'}",
                ephemeral=True)

        @vote.command(name="cancel", description="Commissioner: withdraw an open amendment vote")
        async def vote_cancel(interaction: discord.Interaction, vote_id: int, reason: str) -> None:
            row = bot.store.vote(vote_id)
            if not bot.is_commissioner(interaction.user):
                await interaction.response.send_message("Only the Commissioner can withdraw a vote.", ephemeral=True)
                return
            if row is None or row["status"] != "open" or row["kind"] not in ("amendment", "services"):
                await interaction.response.send_message(
                    "Only an open amendment vote can be withdrawn. Removal and election votes run to the end.",
                    ephemeral=True)
                return
            bot.store.close_vote(vote_id, {"cancelled": True, "reason": reason}, now=utcnow(), status="cancelled")
            if row["proposal_id"] is not None:
                bot.store.set_proposal_status(int(row["proposal_id"]), "withdrawn")
            channel = await bot.channel(row["channel_id"])
            if channel:
                await channel.send(f"Vote #{vote_id} (**{row['title']}**) was withdrawn by the Commissioner: {reason}")
            await interaction.response.send_message("Withdrawn.", ephemeral=True)

        names = [app_commands.Choice(name=f.name, value=f.name) for f in self.cfg.franchises][:25]

        @franchise.command(name="orphan", description="Commissioner: mark a franchise orphaned or filled (2.3)")
        @app_commands.choices(team=names)
        async def franchise_orphan(interaction: discord.Interaction, team: app_commands.Choice[str], orphaned: bool) -> None:
            if not bot.is_commissioner(interaction.user):
                await interaction.response.send_message("Only the Commissioner can change this.", ephemeral=True)
                return
            bot.store.set_orphaned(team.value, orphaned, interaction.user.id, now=utcnow())
            state = "orphaned and has no vote" if orphaned else "active and votes again"
            await interaction.response.send_message(f"{team.value} is now {state}.", ephemeral=True)

        @panel.command(name="draw", description="Draw a three-owner Review Panel for an appeal (19.4)")
        @app_commands.describe(ruling="The ruling being appealed",
                               affected="Affected franchises, separated by commas")
        async def panel_draw(interaction: discord.Interaction, ruling: str, affected: str) -> None:
            if not (bot.is_commissioner(interaction.user) or bot.is_assistant(interaction.user)):
                await interaction.response.send_message("Only the Commissioner or an Assistant Commissioner can draw a panel.",
                                                        ephemeral=True)
                return
            known = {f.name.lower(): f.name for f in bot.cfg.franchises}
            excluded = {known[x.strip().lower()] for x in affected.split(",") if x.strip().lower() in known}
            guild = interaction.guild
            pool: dict[str, list[int]] = {}
            for f in bot.franchises():
                role = guild.get_role(f.role_id) if guild and f.role_id > 0 else None
                members = [m.id for m in (role.members if role else [])
                           if not bot.cfg.owner_role_id or bot.cfg.owner_role_id in bot.role_ids(m)]
                pool[f.name] = members
            try:
                picks = rules.draw_panel(pool, excluded, bot.rng)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
            now = utcnow()
            eligible = sorted(n for n, m in pool.items() if n not in excluded and m)
            bot.store.log(interaction.user.id, "panel_draw", {"ruling": ruling, "picks": picks, "pool": eligible}, now=now)
            channel = await bot.channel(bot.cfg.rulings_log_channel_id) or interaction.channel
            await channel.send(embed=discord.Embed.from_dict(embeds.panel(ruling, eligible, sorted(excluded), picks, now)),
                               allowed_mentions=discord.AllowedMentions(users=True))
            await interaction.response.send_message("Panel drawn and recorded.", ephemeral=True)

        for group in (proposal, vote, franchise, panel):
            self.tree.add_command(group)
