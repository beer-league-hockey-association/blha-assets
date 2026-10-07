"""Discord layer for the BLHA League Bot (discord.py 2.x).

Slash commands:
  /proposal new            post a written amendment proposal (20.2)
  /proposal from-thread    Commissioner turns a suggestion forum thread into a proposal
  /vote open               Commissioner opens voting on a proposal (20.3)
  /vote elect              any Franchise Owner starts an Interim or permanent
                           Commissioner election (19.5)
  /vote status             who has voted so far (not how)
  /vote cancel             Commissioner withdraws an amendment vote
  /franchise orphan        Commissioner marks a franchise orphaned (2.3)
  /panel draw              Commissioner or an Assistant draws a Review Panel (19.4)
  /rule                    look up the Constitution by section, article or keyword
  /deadlines               the next League Calendar dates
  /minor                   is a player BLHA minor-eligible (Article VII)
  /myteam                  your franchise at a glance (private)
  /tradecheck              Constitution compliance for a proposed trade (never value)
  /pickem leaderboard      Pick'em season standings

Ballots are buttons on the vote post. They are private, can be changed until
the vote closes, and close automatically after the window. The same one-minute
ticker posts, locks and scores the weekly Pick'em.

League logic lives in the pure modules next to this one (rules, constitution,
deadlines, minor, team, trade, pickem); blocking reads (Fantrax, the NHL API,
the League Ledger CSV, events.yaml) run in threads through league_data.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import discord
from discord import app_commands
from discord.ext import tasks

from . import constitution, deadlines, embeds, minor, pickem, rules, trade
from . import team as team_view
from .config import BotConfig
from .league_data import LeagueData, NHLLookup
from .store import Store, parse

from blha import season  # noqa: E402  (automation/ is on sys.path via .league_data -> .shared)

log = logging.getLogger("blha.bot")
PICKEM_RETRY = timedelta(minutes=15)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def fantrax_phase() -> tuple[str | None, datetime | None]:
    """(phase, start of Week 1 if it is still ahead) from Fantrax; (None, None) on failure."""
    try:
        from blha.fantrax import Fantrax
        from blha.league import load_league

        info = Fantrax(str(load_league()["league_id"]), user_agent="BLHA-LeagueBot/1.0").league_info()
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

    def __init__(self, bot: "VoteBot", kind: str, proposed_by: str, *, title_default: str | None = None,
                 source: discord.Thread | None = None) -> None:
        super().__init__()
        self.bot, self.kind, self.proposed_by, self.source = bot, kind, proposed_by, source
        if title_default:
            self.prop_title.default = title_default[:100]

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not str(self.season.value).isdigit():
            await interaction.response.send_message("The Season must be a year, like 2029.", ephemeral=True)
            return
        await self.bot.post_proposal(interaction, self.kind, str(self.prop_title.value), str(self.affected.value),
                                     str(self.replacement.value), int(str(self.season.value)), self.proposed_by,
                                     source=self.source)


class PickemPostView(discord.ui.View):
    """The persistent "Make my picks" button on every weekly Pick'em post."""

    def __init__(self, bot: "VoteBot") -> None:
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Make my picks", style=discord.ButtonStyle.primary, custom_id="blha:pickem:make")
    async def make(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.bot.open_picks(interaction)


class PickemPicksView(discord.ui.View):
    """A member's private picks: one menu per matchup, four per page, page buttons on the fifth row."""

    def __init__(self, bot: "VoteBot", season_key: str, number: int, matchups: list[pickem.Matchup],
                 locks_at: datetime, user_id: int, page: int = 0) -> None:
        super().__init__(timeout=900)
        self.bot, self.season_key, self.number = bot, season_key, number
        self.matchups, self.locks_at, self.user_id = matchups, locks_at, user_id
        self.pages = pickem.pages(matchups)
        self.page = max(0, min(page, len(self.pages) - 1))
        self.mine = bot.store.user_picks(season_key, number, user_id)
        for row, m in enumerate(self.pages[self.page]):
            select = discord.ui.Select(
                placeholder=embeds.clip(f"{m.away} at {m.home}", 150), min_values=1, max_values=1, row=row,
                options=[discord.SelectOption(label=embeds.clip(m.away, 100), value=m.away_id, description="Away",
                                              default=self.mine.get(m.key) == m.away_id),
                         discord.SelectOption(label=embeds.clip(m.home, 100), value=m.home_id, description="Home",
                                              default=self.mine.get(m.key) == m.home_id)])
            select.callback = self._picked(m, select)
            self.add_item(select)
        if len(self.pages) > 1:
            for label, target in (("Previous", self.page - 1), ("Next", self.page + 1)):
                button = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, row=4,
                                           disabled=not 0 <= target < len(self.pages))
                button.callback = self._turn(target)
                self.add_item(button)

    def content(self) -> str:
        return pickem.picks_content(self.number, self.matchups, self.mine, self.locks_at, self.page, len(self.pages))

    def again(self, page: int | None = None) -> "PickemPicksView":
        return PickemPicksView(self.bot, self.season_key, self.number, self.matchups, self.locks_at, self.user_id,
                               self.page if page is None else page)

    def _picked(self, m: pickem.Matchup, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction) -> None:
            await self.bot.save_pick(interaction, self, m, select.values[0])
        return callback

    def _turn(self, page: int):
        async def callback(interaction: discord.Interaction) -> None:
            view = self.again(page)
            await interaction.response.edit_message(content=view.content(), view=view)
            self.stop()
        return callback


class VoteBot(discord.Client):
    def __init__(self, cfg: BotConfig, store: Store, data: LeagueData | None = None,
                 nhl: NHLLookup | None = None) -> None:
        intents = discord.Intents.default()
        intents.members = True  # Review Panel draws read role members
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.cfg = cfg
        self.store = store
        self.data = data or LeagueData()
        self._nhl = nhl
        self.tree = app_commands.CommandTree(self)
        self.rng = random.SystemRandom()
        self._pickem_after: datetime | None = None
        self._build_commands()

    # -- helpers -----------------------------------------------------------
    def franchises(self) -> list[rules.Franchise]:
        orphaned = self.store.orphaned()
        return [replace(f, orphaned=f.name in orphaned) for f in self.cfg.franchises]

    @property
    def nhl(self) -> NHLLookup:
        if self._nhl is None:
            self._nhl = NHLLookup()
        return self._nhl

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

    def member_team(self, member: Any, *, needs_fantrax: bool = False) -> tuple[rules.Franchise | None, str | None]:
        """The franchise of a Franchise Owner or Co-Owner (for /myteam and /tradecheck)."""
        return rules.team_member(self.role_ids(member), self.cfg.member_role_ids, self.franchises(),
                                 needs_fantrax=needs_fantrax)

    async def channel(self, channel_id: int | None) -> discord.abc.Messageable | None:
        if not channel_id:
            return None
        return self.get_channel(channel_id) or await self.fetch_channel(channel_id)

    # -- lifecycle ---------------------------------------------------------
    async def setup_hook(self) -> None:
        for vote in self.store.open_votes():
            if vote["message_id"]:
                self.add_view(VoteView(self, as_dict(vote)), message_id=int(vote["message_id"]))
        self.add_view(PickemPostView(self))  # one handler for every Pick'em post's button
        if self.cfg.guild_id:
            guild = discord.Object(id=self.cfg.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        self.ticker.start()

    async def on_ready(self) -> None:
        log.info("BLHA League Bot logged in as %s; %d open votes", self.user, len(self.store.open_votes()))
        for problem in self.cfg.problems:
            log.warning("Config: %s", problem)
        if self.cfg.suggestions_forum_id:
            forum = self.get_channel(self.cfg.suggestions_forum_id)
            if isinstance(forum, discord.ForumChannel):
                # Discord has no "Copy ID" for forum tags, so list them for scheduled_for_vote_tag_id.
                log.info("Suggestions forum tags: %s",
                         ", ".join(f"{t.name} ({t.id})" for t in forum.available_tags) or "none")
                tag_id = self.cfg.scheduled_for_vote_tag_id
                if tag_id and forum.get_tag(tag_id) is None:
                    log.warning("Config: scheduled_for_vote_tag_id %s isn't a tag in the suggestions forum.", tag_id)
            else:
                log.warning("Config: suggestions_forum_id isn't a forum channel the bot can see.")
        try:
            info = await asyncio.to_thread(self.data.league_info)
            for problem in rules.fantrax_id_problems(self.cfg.franchises, team_view.team_names(info)):
                log.warning("Config: %s", problem)
        except Exception as exc:
            log.warning("Could not check fantrax_team_ids against Fantrax: %s", exc)

    @tasks.loop(minutes=1)
    async def ticker(self) -> None:
        now = utcnow()
        for vote in self.store.due_reminder(now, self.cfg.remind_hours):
            await self.send_reminder(as_dict(vote))
        for vote in self.store.due_to_close(now):
            await self.close_vote(as_dict(vote))
        if self.cfg.pickem_channel_id and (self._pickem_after is None or now >= self._pickem_after):
            try:
                await self.pickem_tick(now)
            except Exception:  # never let Pick'em stop the vote ticker
                log.exception("Pick'em check failed; trying again in 15 minutes")
                self._pickem_after = now + PICKEM_RETRY

    @ticker.before_loop
    async def _wait(self) -> None:
        await self.wait_until_ready()

    # -- actions -----------------------------------------------------------
    async def post_proposal(self, interaction: discord.Interaction, kind: str, title: str, affected: str,
                            replacement: str, season_year: int, proposed_by: str,
                            source: discord.Thread | None = None) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        now = utcnow()
        pid = self.store.add_proposal(title=title, affected_rule=affected, replacement=replacement,
                                      effective_season=season_year, kind=kind, proposed_by=proposed_by,
                                      user_id=interaction.user.id, now=now)
        row = as_dict(self.store.proposal(pid))
        opens = now + timedelta(days=self.cfg.settings.notice_days)
        channel = await self.channel(self.cfg.voting_channel_id)
        embed = embeds.proposal(row, opens, source.jump_url if source is not None else None)
        msg = await channel.send(embed=discord.Embed.from_dict(embed))
        self.store.set_proposal_message(pid, msg.channel.id, msg.id)
        note = ""
        if source is not None:
            note = await self.link_suggestion(source, pid, msg.jump_url, interaction.user.id)
        await interaction.followup.send(f"Proposal #{pid} posted in {msg.jump_url}.{note}", ephemeral=True)

    async def link_suggestion(self, thread: discord.Thread, pid: int, url: str, user_id: int) -> str:
        """Reply in the suggestion thread with the proposal link and tag it, if a tag is configured."""
        problems = []
        try:
            await thread.send(f"This suggestion is now **Proposal #{pid}**: {url}")
        except discord.HTTPException as exc:
            problems.append(f"couldn't post in the thread ({exc.status})")
        tag_id = self.cfg.scheduled_for_vote_tag_id
        if tag_id:
            forum = thread.parent or self.get_channel(thread.parent_id)
            tag = forum.get_tag(tag_id) if isinstance(forum, discord.ForumChannel) else None
            if tag is None:
                problems.append("scheduled_for_vote_tag_id isn't a tag in that forum")
            elif tag not in thread.applied_tags:
                try:
                    await thread.add_tags(tag, reason=f"Became Proposal #{pid}")
                except discord.HTTPException as exc:
                    problems.append(f"couldn't add the tag ({exc.status})")
        self.store.log(user_id, "proposal_from_thread", {"proposal": pid, "thread": thread.id}, now=utcnow())
        return f" Note: {'; '.join(problems)}." if problems else " The suggestion thread links to it."

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

    # -- Pick'em -----------------------------------------------------------
    async def pickem_tick(self, now: datetime) -> None:
        """Post, lock and score Pick'em Weeks from the Fantrax calendar (pickem.plan)."""
        info = await asyncio.to_thread(self.data.league_info)
        league_id = await asyncio.to_thread(getattr, self.data, "league_id")
        key = pickem.season_key(league_id, info)
        for action, number in pickem.plan(info, now, self.cfg.timezone, self.store.pickem_statuses(key)):
            if action == "score":
                await self.pickem_score(key, info, number, now)
            elif action == "lock":
                self.store.set_pickem_status(key, number, "locked")
                await self.pickem_remove_button(self.store.pickem_week(key, number))
            elif action == "post":
                await self.pickem_post(key, info, number, now)

    async def pickem_post(self, key: str, info: dict[str, Any], number: int, now: datetime) -> None:
        week = season.period(info, number)
        ms = pickem.matchups(info, number)
        channel = await self.channel(self.cfg.pickem_channel_id)
        if week is None or not ms or channel is None:
            return
        msg = await channel.send(embed=discord.Embed.from_dict(pickem.post_embed(number, ms, week.start)),
                                 view=PickemPostView(self))
        self.store.add_pickem_week(key, number, [m.as_dict() for m in ms], locks_at=week.start, now=now)
        self.store.set_pickem_message(key, number, msg.channel.id, msg.id)
        log.info("Pick'em Week %s posted", number)

    async def pickem_remove_button(self, row: Any) -> None:
        if row is None or not row["message_id"]:
            return
        try:
            channel = await self.channel(int(row["channel_id"]))
            message = await channel.fetch_message(int(row["message_id"]))
            await message.edit(view=None)
        except Exception as exc:
            log.warning("Could not remove the Pick'em button for Week %s: %s", row["period"], exc)

    def pickem_board(self, key: str) -> tuple[list[tuple[int, int, int]], int]:
        scored = self.store.scored_weeks(key)
        weeks = [pickem.weekly(self.store.week_picks(key, number), won) for number, won in scored]
        return pickem.leaderboard(weeks), len(scored)

    async def pickem_score(self, key: str, info: dict[str, Any], number: int, now: datetime) -> None:
        row = self.store.pickem_week(key, number)
        week = season.period(info, number)
        if row is None or week is None:
            return
        ms = [pickem.Matchup.from_dict(d) for d in json.loads(row["matchups"])]
        scores = await asyncio.to_thread(self.data.matchup_scores, number)
        won = pickem.winners(ms, scores)
        if not pickem.ready_to_score(ms, won, now, season.final_at(week, self.cfg.timezone)):
            return
        self.store.set_pickem_status(key, number, "scored", winners=won, now=now)
        if row["status"] == "open":
            await self.pickem_remove_button(row)
        results = pickem.weekly(self.store.week_picks(key, number), won)
        if not results:
            return  # nobody played: no results post
        board, _ = self.pickem_board(key)
        channel = await self.channel(self.cfg.pickem_channel_id)
        if channel is not None:
            embed = pickem.results_embed(number, ms, won, results, board, pickem.season_label(key))
            await channel.send(embed=discord.Embed.from_dict(embed))
        log.info("Pick'em Week %s scored", number)

    async def open_picks(self, interaction: discord.Interaction) -> None:
        row = self.store.pickem_week_by_message(interaction.message.id) if interaction.message else None
        if row is None:
            await interaction.response.send_message("This Pick'em post is no longer active.", ephemeral=True)
            return
        if not self.cfg.pickem_role_ids & self.role_ids(interaction.user):
            who = " or ".join({"owner": "Franchise Owners", "co_owner": "Co-Owners"}[p] for p in self.cfg.pickem_players)
            await interaction.response.send_message(f"Pick'em is for {who or 'members with a franchise role'}.",
                                                    ephemeral=True)
            return
        locks_at = parse(row["locks_at"])
        if row["status"] != "open" or pickem.is_locked(locks_at, utcnow()):
            await interaction.response.send_message(f"Week {row['period']} picks are locked.", ephemeral=True)
            return
        ms = [pickem.Matchup.from_dict(d) for d in json.loads(row["matchups"])]
        view = PickemPicksView(self, row["season"], int(row["period"]), ms, locks_at, interaction.user.id)
        await interaction.response.send_message(view.content(), view=view, ephemeral=True)

    async def save_pick(self, interaction: discord.Interaction, view: PickemPicksView, m: pickem.Matchup,
                        team_id: str) -> None:
        now = utcnow()
        row = self.store.pickem_week(view.season_key, view.number)
        if row is None or row["status"] != "open" or pickem.is_locked(view.locks_at, now):
            await interaction.response.edit_message(content=f"Week {view.number} picks are locked.", view=None)
            view.stop()
            return
        if team_id not in (m.away_id, m.home_id):
            await interaction.response.send_message("That team isn't in this matchup.", ephemeral=True)
            return
        self.store.pick(view.season_key, view.number, interaction.user.id, m.key, team_id, now=now)
        fresh = view.again()
        await interaction.response.edit_message(content=fresh.content(), view=fresh)
        view.stop()

    # -- commands ----------------------------------------------------------
    def _build_commands(self) -> None:
        bot = self
        proposal = app_commands.Group(name="proposal", description="Amendment proposals (Article XX)", guild_only=True)
        vote = app_commands.Group(name="vote", description="League votes", guild_only=True)
        franchise = app_commands.Group(name="franchise", description="Franchise status", guild_only=True)
        panel = app_commands.Group(name="panel", description="Review Panel (19.4)", guild_only=True)
        pickem_group = app_commands.Group(name="pickem", description="Weekly Pick'em", guild_only=True)
        kinds = [app_commands.Choice(name="Material Amendment", value="amendment"),
                 app_commands.Choice(name="League Services Allocation change", value="services")]

        @proposal.command(name="new", description="Post a written amendment proposal (20.2)")
        @app_commands.describe(kind="Use 'services' only to change the League Services Allocation (3.6)")
        @app_commands.choices(kind=kinds)
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

        @proposal.command(name="from-thread", description="Commissioner: turn this suggestion thread into a proposal")
        @app_commands.describe(kind="Use 'services' only to change the League Services Allocation (3.6)")
        @app_commands.choices(kind=kinds)
        async def proposal_from_thread(interaction: discord.Interaction, kind: app_commands.Choice[str]) -> None:
            if not bot.is_commissioner(interaction.user):
                await interaction.response.send_message("Only the Commissioner can turn a suggestion into a proposal.",
                                                        ephemeral=True)
                return
            if not bot.cfg.suggestions_forum_id:
                await interaction.response.send_message(
                    "Set discord.suggestions_forum_id in the bot config first.", ephemeral=True)
                return
            thread = interaction.channel
            if not isinstance(thread, discord.Thread) or thread.parent_id != bot.cfg.suggestions_forum_id:
                await interaction.response.send_message("Use this inside a thread in the suggestions forum.",
                                                        ephemeral=True)
                return
            await interaction.response.send_modal(
                ProposalModal(bot, kind.value, "Commissioner", title_default=thread.name, source=thread))

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

        @vote.command(name="elect", description="Elect an Interim or permanent Commissioner (19.5)")
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
                    "Only an open amendment vote can be withdrawn. Election votes run to the end.",
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

        @pickem_group.command(name="leaderboard", description="Pick'em standings for the Season")
        async def pickem_leaderboard(interaction: discord.Interaction) -> None:
            key = bot.store.latest_pickem_season()
            if key is None:
                embed = pickem.leaderboard_embed([], "This Season", 0)
            else:
                board, weeks = bot.pickem_board(key)
                embed = pickem.leaderboard_embed(board, pickem.season_label(key), weeks)
            await interaction.response.send_message(embed=discord.Embed.from_dict(embed))

        @app_commands.command(name="rule", description="Look up the Constitution by section (12.4), article (XII) or keyword")
        @app_commands.describe(query="A section like 12.4, an article like XII, or a keyword like prepayment",
                               ephemeral="Only you see the answer")
        @app_commands.guild_only()
        async def rule(interaction: discord.Interaction, query: str, ephemeral: bool = False) -> None:
            answer = await asyncio.to_thread(constitution.answer, query)
            if answer.message:
                await interaction.response.send_message(answer.message, ephemeral=True)
                return
            await interaction.response.send_message(embeds=[discord.Embed.from_dict(e) for e in answer.embeds],
                                                    ephemeral=ephemeral)

        @app_commands.command(name="deadlines", description="The next 3 dates on the League Calendar")
        @app_commands.describe(ephemeral="Only you see the answer")
        @app_commands.guild_only()
        async def deadlines_cmd(interaction: discord.Interaction, ephemeral: bool = False) -> None:
            try:
                events = await asyncio.to_thread(bot.data.events)
            except Exception as exc:
                log.warning("Could not read events.yaml: %s", exc)
                await interaction.response.send_message("Couldn't read the League Calendar right now.", ephemeral=True)
                return
            found = deadlines.upcoming(events, utcnow(), 3)
            await interaction.response.send_message(embed=discord.Embed.from_dict(deadlines.embed(found)),
                                                    ephemeral=ephemeral)

        @app_commands.command(name="minor", description="Is a player BLHA minor-eligible? Age and NHL games (Article VII)")
        @app_commands.describe(player="Player name, e.g. Macklin Celebrini",
                               team="NHL team if two players share the name, e.g. CAR",
                               ephemeral="Only you see the answer")
        @app_commands.guild_only()
        async def minor_cmd(interaction: discord.Interaction, player: str, team: Optional[str] = None,
                            ephemeral: bool = False) -> None:
            await interaction.response.defer(ephemeral=ephemeral, thinking=True)
            now = utcnow()

            def work() -> tuple[dict[str, Any] | None, str | None]:
                try:
                    info = bot.data.league_info()
                except Exception as exc:  # opening day falls back to an estimate
                    log.warning("Fantrax unavailable for /minor: %s", exc)
                    info = None
                return minor.lookup(bot.nhl, info, player, team, now, bot.cfg.timezone)

            try:
                embed, message = await asyncio.to_thread(work)
            except Exception as exc:
                log.warning("/minor lookup failed: %s", exc)
                await interaction.followup.send("Couldn't reach the NHL's stats service right now. Try again later.")
                return
            if embed is None:
                await interaction.followup.send(message or "No match.")
            else:
                await interaction.followup.send(embed=discord.Embed.from_dict(embed))

        @app_commands.command(name="myteam", description="Your franchise: roster limits, picks, ledger and this Week")
        @app_commands.guild_only()
        async def myteam(interaction: discord.Interaction) -> None:
            f, why = bot.member_team(interaction.user, needs_fantrax=True)
            if f is None:
                await interaction.response.send_message(why, ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            embed = await asyncio.to_thread(team_view.build, bot.data, f.name, f.fantrax_team_id, utcnow(), bot.cfg.timezone)
            await interaction.followup.send(embed=discord.Embed.from_dict(embed), ephemeral=True)

        @app_commands.command(name="tradecheck", description="Check a trade against the Constitution (compliance only, never value)")
        @app_commands.describe(team_a="First franchise", team_b="Second franchise",
                               a_players="Players the first franchise gives, comma-separated",
                               a_picks="Picks the first franchise gives, e.g. 2029 1st, 2028 3rd",
                               b_players="Players the second franchise gives, comma-separated",
                               b_picks="Picks the second franchise gives, e.g. 2029 1st, 2028 3rd",
                               to_minors="Incoming players the new team would put in minors, comma-separated",
                               post="Post the result in this channel instead of only to you")
        @app_commands.choices(team_a=names, team_b=names)
        @app_commands.guild_only()
        async def tradecheck(interaction: discord.Interaction, team_a: app_commands.Choice[str],
                             team_b: app_commands.Choice[str], a_players: str = "", a_picks: str = "",
                             b_players: str = "", b_picks: str = "", to_minors: str = "", post: bool = False) -> None:
            mine, why = bot.member_team(interaction.user)
            if mine is None and not bot.is_commissioner(interaction.user):
                await interaction.response.send_message(why, ephemeral=True)
                return
            if team_a.value == team_b.value:
                await interaction.response.send_message("Pick two different franchises.", ephemeral=True)
                return
            if not any(x.strip() for x in (a_players, a_picks, b_players, b_picks)):
                await interaction.response.send_message("List at least one player or pick that changes hands.",
                                                        ephemeral=True)
                return
            by_name = {f.name: f for f in bot.franchises()}
            fa, fb = by_name.get(team_a.value), by_name.get(team_b.value)
            if fa is None or fb is None or not fa.fantrax_team_id or not fb.fantrax_team_id:
                await interaction.response.send_message(
                    "Both franchises need a fantrax_team_id in the bot config. Ask the Commissioner.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=not post, thinking=True)
            a = trade.Side(fa.name, fa.fantrax_team_id, a_players, a_picks)
            b = trade.Side(fb.name, fb.fantrax_team_id, b_players, b_picks)
            embed = await asyncio.to_thread(trade.build, bot.data, a, b, to_minors, utcnow(), bot.cfg.timezone)
            await interaction.followup.send(embed=discord.Embed.from_dict(embed), ephemeral=not post)

        for group in (proposal, vote, franchise, panel, pickem_group):
            self.tree.add_command(group)
        for command in (rule, deadlines_cmd, minor_cmd, myteam, tradecheck):
            self.tree.add_command(command)
