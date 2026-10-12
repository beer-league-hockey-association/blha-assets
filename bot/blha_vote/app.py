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
  /pool boxes              the Playoff Pool boxes (just for fun, during the NHL playoffs)
  /pool pick               a franchise picks one player per box (private, until the first puck drop)
  /pool export             Commissioner, after the deadline: the picks as entries.yaml for the pool automation
  /book lines|bet|mybets|leaderboard
                           BLHA Bucks: play-money bets against the spread on
                           matchups the bettor's franchise isn't in
  /awards open|nominate|close|results|status
                           the annual Awards Ballot (5-3-1), after the Championship

Ballots are buttons on the vote post. They are private, can be changed until
the vote closes, and close automatically after the window. The same one-minute
ticker posts, locks and scores the weekly Pick'em, posts, locks and settles
BLHA Bucks Weeks, and closes the Awards Ballot at its deadline.

League logic lives in the pure modules next to this one (rules, constitution,
deadlines, minor, team, trade, pickem, pool, book, awards); blocking reads (Fantrax,
the NHL API, the League Ledger CSV, events.yaml, the Playoff Pool boxes) run in
threads through league_data.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import random
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import discord
from discord import app_commands
from discord.ext import tasks

from . import awards, book, constitution, deadlines, embeds, minor, pickem, rules, trade
from . import pool as pool_view
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


class PoolPicksView(discord.ui.View):
    """A franchise's private Playoff Pool picks: one menu per box, four per page, page buttons on the fifth row."""

    def __init__(self, bot: "VoteBot", boxes: Any, franchise: str, page: int = 0) -> None:
        super().__init__(timeout=900)
        self.bot, self.boxes, self.franchise = bot, boxes, franchise
        self.pages = pool_view.pages(boxes)
        self.page = max(0, min(page, len(self.pages) - 1))
        self.mine = bot.store.pool_picks(boxes.year, franchise)
        for row, box in enumerate(self.pages[self.page]):
            options = []
            for index, player in enumerate(box.players[:25], 1):
                label, description = pool_view.option(index, player)
                options.append(discord.SelectOption(label=label, value=str(player.id), description=description,
                                                    default=self.mine.get(box.number) == player.id))
            select = discord.ui.Select(placeholder=embeds.clip(box.title, 150), min_values=1, max_values=1,
                                       row=row, options=options)
            select.callback = self._picked(box.number, select)
            self.add_item(select)
        if len(self.pages) > 1:
            for label, target in (("Previous", self.page - 1), ("Next", self.page + 1)):
                button = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, row=4,
                                           disabled=not 0 <= target < len(self.pages))
                button.callback = self._turn(target)
                self.add_item(button)

    def content(self) -> str:
        return pool_view.picks_content(self.boxes, self.franchise, self.mine, self.page, len(self.pages))

    def again(self, page: int | None = None) -> "PoolPicksView":
        return PoolPicksView(self.bot, self.boxes, self.franchise, self.page if page is None else page)

    def _picked(self, box_number: int, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction) -> None:
            await self.bot.save_pool_pick(interaction, self, box_number, int(select.values[0]))
        return callback

    def _turn(self, page: int):
        async def callback(interaction: discord.Interaction) -> None:
            view = self.again(page)
            await interaction.response.edit_message(content=view.content(), view=view)
            self.stop()
        return callback


class AwardsPostView(discord.ui.View):
    """The persistent "Fill out my ballot" button on the Awards Ballot post."""

    def __init__(self, bot: "VoteBot") -> None:
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Fill out my ballot", style=discord.ButtonStyle.primary, custom_id="blha:awards:ballot")
    async def fill(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.bot.open_awards_ballot(interaction)


class AwardsBallotView(discord.ui.View):
    """A franchise's private Awards ballot: one award per page, a menu each for 1st, 2nd and 3rd."""

    def __init__(self, bot: "VoteBot", season_year: int, franchise: str, nominees: awards.Nominees,
                 closes_at: datetime, page: int = 0, *, at: str | None = None) -> None:
        super().__init__(timeout=900)
        self.bot, self.season, self.franchise = bot, season_year, franchise
        self.nominees, self.closes_at = nominees, closes_at
        self.keys = [a.key for a in awards.AWARDS if nominees.get(a.key)]
        if at in self.keys:
            page = self.keys.index(at)
        self.page = max(0, min(page, len(self.keys) - 1))
        self.award = awards.BY_KEY[self.keys[self.page]] if self.keys else None
        self.mine: dict[int, str] = {}
        self.options: list[awards.Nominee] = []
        if self.award is None:
            return
        self.mine = bot.store.awards_ballot(season_year, franchise).get(self.award.key, {})
        self.options = awards.options_for(self.award, nominees[self.award.key], franchise)
        for place in (awards.PLACES if self.options else ()):
            select = discord.ui.Select(
                placeholder=f"{awards.ORDINAL[place]} choice ({awards.POINTS[place]} points)",
                min_values=1, max_values=1, row=place - 1,
                options=[discord.SelectOption(label=embeds.clip(n.label, 100), value=n.id,
                                              description=embeds.clip(n.subtitle, 100) or None,
                                              default=self.mine.get(place) == n.id) for n in self.options])
            select.callback = self._picked(place, select)
            self.add_item(select)
        for label, target in (("Previous", self.page - 1), ("Next", self.page + 1)):
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, row=3,
                                       disabled=not 0 <= target < len(self.keys))
            button.callback = self._turn(target)
            self.add_item(button)
        clear = discord.ui.Button(label="Clear this award", style=discord.ButtonStyle.danger, row=3,
                                  disabled=not self.mine)
        clear.callback = self._clear
        self.add_item(clear)

    def content(self) -> str:
        if self.award is None:
            return f"Season {self.season} Awards: no award has nominees yet."
        return awards.ballot_content(self.season, self.award, self.nominees[self.award.key], self.mine,
                                     self.franchise, self.closes_at, self.page, len(self.keys),
                                     can_rank=bool(self.options))

    def again(self, page: int | None = None, nominees: awards.Nominees | None = None) -> "AwardsBallotView":
        """A fresh copy (after a change), staying on the same award even if nominees were added meanwhile."""
        if page is not None:
            return AwardsBallotView(self.bot, self.season, self.franchise, nominees or self.nominees,
                                    self.closes_at, page)
        return AwardsBallotView(self.bot, self.season, self.franchise, nominees or self.nominees, self.closes_at,
                                self.page, at=self.award.key if self.award else None)

    def _picked(self, place: int, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction) -> None:
            await self.bot.save_award_choice(interaction, self, place, select.values[0])
        return callback

    def _turn(self, page: int):
        async def callback(interaction: discord.Interaction) -> None:
            view = self.again(page)
            await interaction.response.edit_message(content=view.content(), view=view)
            self.stop()
        return callback

    async def _clear(self, interaction: discord.Interaction) -> None:
        await self.bot.save_award_choice(interaction, self, None, None)


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
        self._book_after: datetime | None = None
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
        self.add_view(AwardsPostView(self))  # and for every Awards Ballot post's button
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
        if self.cfg.book_channel_id and (self._book_after is None or now >= self._book_after):
            try:
                await self.book_tick(now)
            except Exception:  # never let BLHA Bucks stop the vote ticker
                log.exception("BLHA Bucks check failed; trying again in 15 minutes")
                self._book_after = now + PICKEM_RETRY
        for row in self.store.awards_due_to_close(now):
            try:
                await self.close_awards_ballot(row, now)
            except Exception:
                log.exception("Closing the Season %s Awards Ballot failed", row["season"])

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

    # -- Playoff Pool ------------------------------------------------------
    async def pool_entries_via(self) -> str:
        """playoff_pool.entries_via in automation/league.yaml: pool_view.BOT or pool_view.DM."""
        return await asyncio.to_thread(self.data.pool_entries_via)

    async def pool_boxes_or_reply(self, interaction: discord.Interaction, max_age: float | None = None) -> Any:
        """The posted boxes, or None after telling the member why not (the interaction is deferred)."""
        try:
            boxes = await asyncio.to_thread(self.data.pool_boxes, max_age)
        except Exception as exc:
            log.warning("Could not read the Playoff Pool boxes: %s", exc)
            await interaction.followup.send("Couldn't read the Playoff Pool boxes right now. Try again later.",
                                            ephemeral=True)
            return None
        if boxes is None:
            await interaction.followup.send(pool_view.NOT_POSTED, ephemeral=True)
        return boxes

    async def save_pool_pick(self, interaction: discord.Interaction, view: PoolPicksView, box_number: int,
                             player_id: int) -> None:
        edit, reply = interaction.response.edit_message, interaction.response.send_message
        if view.boxes.deadline is None:
            # This menu opened before boxes.json had the deadline (it is cached for 10 minutes), and the
            # first puck drop may have been published, or passed, since: read the file again first.
            await interaction.response.defer()
            edit, reply = interaction.edit_original_response, interaction.followup.send
            try:
                boxes = await asyncio.to_thread(self.data.pool_boxes, pool_view.RECHECK_SECONDS)
            except Exception as exc:
                log.warning("Could not re-read the Playoff Pool boxes: %s", exc)
                await reply("Couldn't check the pick deadline right now, so that pick wasn't saved. "
                            "Try again in a minute.", ephemeral=True)
                return
            if boxes is not None and boxes.year == view.boxes.year and boxes.deadline is not None:
                view.boxes = boxes
        now = utcnow()
        if view.boxes.locked(now):
            await edit(content="Playoff Pool picks are locked: the playoffs have started.", view=None)
            view.stop()
            return
        if not pool_view.valid_pick(view.boxes, box_number, player_id):
            await reply("That player isn't in this box.", ephemeral=True)
            return
        self.store.pool_pick(view.boxes.year, view.franchise, box_number, player_id, interaction.user.id, now=now,
                             box_count=len(view.boxes.boxes))
        fresh = view.again()
        await edit(content=fresh.content(), view=fresh)
        view.stop()

    # -- season roles --------------------------------------------------------
    async def award_season_role(self, role_name: str, winners: list[int], reason: str) -> str | None:
        """Give a season role (the BLHA Bucks Sharp role) to the winners and take it from last Season's holders.

        Needs Manage Roles, with the bot's own role above this one. Returns what
        went wrong, or None when every change went through.
        """
        guild = self.get_guild(self.cfg.guild_id) if self.cfg.guild_id else None
        if guild is None:
            return "the bot can't see the server (discord.guild_id)"
        role = discord.utils.get(guild.roles, name=role_name)
        if role is None:
            return f"the server has no role named {role_name!r}"
        add, remove = book.role_changes((m.id for m in role.members), winners)
        problems = []
        for uid in remove:
            member = guild.get_member(uid)
            try:
                if member is not None:
                    await member.remove_roles(role, reason=reason)
            except discord.HTTPException as exc:
                problems.append(f"couldn't take it from {uid} ({exc.status})")
        for uid in add:
            try:
                member = guild.get_member(uid) or await guild.fetch_member(uid)
                await member.add_roles(role, reason=reason)
            except discord.HTTPException as exc:
                problems.append(f"couldn't give it to {uid} ({exc.status})")
        return "; ".join(problems) or None

    # -- BLHA Bucks ----------------------------------------------------------
    def book_player(self, member: Any) -> tuple[rules.Franchise | None, str | None]:
        """The bettor's franchise (to keep them off its matchup), or why they can't play."""
        if not self.cfg.book_role_ids & self.role_ids(member):
            who = " or ".join({"owner": "Franchise Owners", "co_owner": "Co-Owners"}[p] for p in self.cfg.book_players)
            return None, f"BLHA Bucks is for {who or 'members with a franchise role'}."
        return rules.team_member(self.role_ids(member), self.cfg.book_role_ids, self.franchises(), needs_fantrax=True)

    @staticmethod
    def book_lines_of(row: Any) -> list[book.Line]:
        return [book.Line.from_dict(d) for d in json.loads(row["lines"])]

    def book_bets(self, key: str, number: int) -> list[book.Bet]:
        return [book.Bet(uid, matchup, side, amount, franchise)
                for uid, matchup, side, amount, franchise in self.store.week_bets(key, number)]

    def book_board(self, key: str, settling: tuple[int, list[book.Settled]] | None = None
                   ) -> tuple[list[book.Standing], int]:
        """Season profit standings over the settled Weeks, plus ``settling`` (week, its graded bets) if given."""
        weeks = [book.settle(self.book_bets(key, number), [book.Line.from_dict(d) for d in lines], found)
                 for number, lines, found in self.store.settled_book_weeks(key)
                 if settling is None or number != settling[0]]
        if settling is not None:
            weeks.append(settling[1])
        return book.leaderboard(weeks), len(weeks)

    def open_book_week(self) -> tuple[Any, list[book.Line]]:
        """The Week taking bets right now (row, lines), or (None, [])."""
        row = self.store.latest_book_week("open")
        if row is None or pickem.is_locked(parse(row["locks_at"]), utcnow()):
            return None, []
        return row, self.book_lines_of(row)

    def book_matchup_choices(self, member: Any, current: str) -> list[app_commands.Choice[str]]:
        """/book bet's matchup menu: this Week's lines, never the member's own matchup."""
        row, lines = self.open_book_week()
        if row is None:
            return []
        f, _ = self.book_player(member)
        text = (current or "").lower()
        shown = book.available(lines, f.fantrax_team_id) if f is not None else lines
        return [app_commands.Choice(name=embeds.clip(x.text(), 100), value=x.key)
                for x in shown if text in x.text().lower()][:25]

    def book_side_choices(self, matchup: str) -> list[app_commands.Choice[str]]:
        """/book bet's side menu: the two teams of the chosen matchup, with their spreads."""
        _, lines = self.open_book_week()
        line = next((x for x in lines if x.key == matchup), None)
        if line is None:
            return [app_commands.Choice(name="Away team", value=book.AWAY),
                    app_commands.Choice(name="Home team", value=book.HOME)]
        return [app_commands.Choice(name=embeds.clip(f"{line.label(s)} ({s})", 100), value=s) for s in book.SIDES]

    async def book_tick(self, now: datetime) -> None:
        """Post lines, lock and settle BLHA Bucks Weeks on Pick'em's Fantrax calendar (pickem.plan)."""
        info = await asyncio.to_thread(self.data.league_info)
        league_id = await asyncio.to_thread(getattr, self.data, "league_id")
        key = pickem.season_key(league_id, info)
        for action, number in pickem.plan(info, now, self.cfg.timezone, self.store.book_statuses(key)):
            if action == "score":
                await self.book_settle(key, info, number, now)
            elif action == "lock":
                self.store.set_book_status(key, number, "locked")
            elif action == "post":
                await self.book_post(key, info, number, now)
        await self.book_crown_if_due(key, info)

    async def book_post(self, key: str, info: dict[str, Any], number: int, now: datetime) -> None:
        week = season.period(info, number)
        channel = await self.channel(self.cfg.book_channel_id)
        if week is None or channel is None:
            return
        lines = await asyncio.to_thread(book.lines_for_week, info, number, now, self.cfg.timezone,
                                        self.data.matchup_scores)
        if not lines:
            return
        embed = book.lines_embed(number, lines, week.start, pickem.season_label(key))
        msg = await channel.send(embed=discord.Embed.from_dict(embed))
        self.store.add_book_week(key, number, [line.as_dict() for line in lines], locks_at=week.start, now=now)
        self.store.set_book_message(key, number, msg.channel.id, msg.id)
        log.info("BLHA Bucks Week %s lines posted", number)

    async def book_settle(self, key: str, info: dict[str, Any], number: int, now: datetime) -> None:
        row = self.store.book_week(key, number)
        week = season.period(info, number)
        if row is None or week is None:
            return
        lines = self.book_lines_of(row)
        scores = await asyncio.to_thread(self.data.matchup_scores, number)
        found = book.results(lines, scores)
        if not book.ready_to_settle(lines, found, now, season.final_at(week, self.cfg.timezone)):
            return
        # Post first, then mark the Week settled: if the post fails, the Week stays unsettled and the
        # next tick (15 minutes later) settles and posts it again. It is only ever settled once.
        settled = book.settle(self.book_bets(key, number), lines, found)
        channel = await self.channel(self.cfg.book_channel_id)
        if settled and channel is not None:  # nobody bet: no settlement post
            board, _ = self.book_board(key, settling=(number, settled))
            embed = book.settlement_embed(number, lines, found, settled, board, pickem.season_label(key))
            await channel.send(embed=discord.Embed.from_dict(embed))
        self.store.set_book_status(key, number, "settled", results={k: list(v) for k, v in found.items()}, now=now)
        log.info("BLHA Bucks Week %s settled", number)

    async def book_crown_if_due(self, key: str, info: dict[str, Any]) -> None:
        """Crown the Sharp once the last regular-season Week is settled.

        Checked at the end of every BLHA Bucks tick rather than inside the
        settlement, so a crowning that failed part way (a Discord error) is
        retried on later ticks until it is stored. Does nothing once this
        season's champions are stored.
        """
        if self.store.book_champions(key) is not None:
            return
        last_regular, _, _ = season.playoff_settings(info)
        if not any(n >= last_regular and s == "settled" for n, s in self.store.book_statuses(key).items()):
            return
        board, _ = self.book_board(key)
        await self.book_crown(key, board)

    async def book_crown(self, key: str, board: list[book.Standing]) -> None:
        """After the last regular-season Week: the season profit leader gets the Sharp role (once per season).

        The role and the post come first and the champions are stored last, so
        if the post fails the next tick does both again (giving a role someone
        already has changes nothing).
        """
        if self.store.book_champions(key) is not None:
            return
        leaders = book.season_leaders(board)
        problem = None
        if leaders and self.cfg.sharp_role:
            problem = await self.award_season_role(self.cfg.sharp_role, leaders,
                                                   f"BLHA Bucks {pickem.season_label(key)} profit leader")
        if problem:
            log.warning("BLHA Bucks: the %s role: %s", self.cfg.sharp_role, problem)
        channel = await self.channel(self.cfg.book_channel_id)
        if channel is not None and leaders:
            embed = book.sharp_embed(self.cfg.sharp_role or "Sharp", leaders, board, pickem.season_label(key))
            await channel.send(embed=discord.Embed.from_dict(embed))
        self.store.set_book_champions(key, leaders, now=utcnow())

    # -- Awards Ballot -------------------------------------------------------
    def league_phase(self) -> str | None:
        """Fantrax's phase (preseason, regular, playoffs, offseason), or None if Fantrax can't be read. Blocks."""
        try:
            return season.phase(self.data.league_info(), utcnow())
        except Exception as exc:
            log.warning("Fantrax phase check failed: %s", exc)
            return None

    def final_ranks(self) -> dict[str, int] | None:
        """This Season's regular-season rank per franchise from Fantrax standings, or None. Blocks."""
        try:
            return awards.ranks_by_franchise(self.data.standings(), self.cfg.franchises) or None
        except Exception as exc:
            log.warning("Fantrax standings unavailable for the Awards Ballot: %s", exc)
            return None

    def nominator_franchises(self, member: Any, *, commissioner: bool) -> set[str]:
        """The franchises a nominator may not nominate: their own (and the Commissioner's, for the Commissioner)."""
        own = {f.name for f in self.cfg.franchises if f.role_id in self.role_ids(member)}
        if commissioner:
            own |= {f.name for f in self.cfg.franchises if f.commissioner}
        return own

    def awards_voters(self) -> list[str]:
        return [f.name for f in self.franchises() if not f.orphaned]

    async def open_awards_ballot(self, interaction: discord.Interaction) -> None:
        row = self.store.awards_by_message(interaction.message.id) if interaction.message else None
        if row is None:
            await interaction.response.send_message("This Awards Ballot is no longer active.", ephemeral=True)
            return
        closes = parse(row["closes_at"])
        if row["status"] != "open" or utcnow() >= closes:
            await interaction.response.send_message(f"Season {row['season']} Awards ballots are closed.", ephemeral=True)
            return
        franchise, why = rules.can_cast(self.role_ids(interaction.user), self.cfg.owner_role_id, self.franchises(),
                                        rules.KINDS["amendment"])
        if franchise is None:
            await interaction.response.send_message(why, ephemeral=True)
            return
        view = AwardsBallotView(self, int(row["season"]), franchise.name, awards.nominees_from_json(row["nominees"]),
                                closes)
        await interaction.response.send_message(view.content(), view=view, ephemeral=True)

    async def save_award_choice(self, interaction: discord.Interaction, view: AwardsBallotView, place: int | None,
                                nominee_id: str | None) -> None:
        """Save one 1st/2nd/3rd choice (or, with place None, clear the award) and redraw the ballot."""
        now = utcnow()
        row = self.store.awards_season(view.season)
        if row is None or row["status"] != "open" or now >= parse(row["closes_at"]):
            await interaction.response.edit_message(content=f"Season {view.season} Awards ballots are closed.",
                                                    view=None)
            view.stop()
            return
        franchise, why = rules.can_cast(self.role_ids(interaction.user), self.cfg.owner_role_id, self.franchises(),
                                        rules.KINDS["amendment"])
        if franchise is None or franchise.name != view.franchise:
            await interaction.response.send_message(why or f"This is {view.franchise}'s ballot.", ephemeral=True)
            return
        nominees = awards.nominees_from_json(row["nominees"])  # an Assistant may have added nominees
        award = view.award
        if award is None:
            await interaction.response.send_message("No award has nominees yet.", ephemeral=True)
            return
        if place is None:
            new: dict[int, str] = {}
        else:
            current = self.store.awards_ballot(view.season, view.franchise).get(award.key, {})
            new, error = awards.choose(current, place, nominee_id or "", award, nominees.get(award.key, []),
                                       view.franchise)
            if error:
                await interaction.response.send_message(error, ephemeral=True)
                return
        self.store.set_award_choices(view.season, view.franchise, award.key, new, user_id=interaction.user.id, now=now)
        fresh = view.again(nominees=nominees)
        await interaction.response.edit_message(content=fresh.content(), view=fresh)
        view.stop()

    async def close_awards_ballot(self, row: Any, now: datetime, user_id: int | None = None) -> None:
        """Close the ballot (Commissioner or deadline), remove the button and say what happens next."""
        year = int(row["season"])
        self.store.close_awards(year, now=now, user_id=user_id)
        channel = await self.channel(int(row["channel_id"])) if row["channel_id"] else None
        if channel is None:
            return
        try:
            message = await channel.fetch_message(int(row["message_id"]))
            await message.edit(view=None)
        except Exception as exc:
            log.warning("Could not remove the Awards Ballot button for Season %s: %s", year, exc)
        await channel.send(f"Season {year} Awards ballots are closed. The winners will be announced in "
                           "**🏆│hall-of-champions**.")

    # -- commands ----------------------------------------------------------
    def _build_commands(self) -> None:
        bot = self
        proposal = app_commands.Group(name="proposal", description="Amendment proposals (Article XX)", guild_only=True)
        vote = app_commands.Group(name="vote", description="League votes", guild_only=True)
        franchise = app_commands.Group(name="franchise", description="Franchise status", guild_only=True)
        panel = app_commands.Group(name="panel", description="Review Panel (19.4)", guild_only=True)
        pickem_group = app_commands.Group(name="pickem", description="Weekly Pick'em", guild_only=True)
        pool_group = app_commands.Group(name="pool", description="Playoff Pool (just for fun, no money)",
                                        guild_only=True)
        book_group = app_commands.Group(name="book", description="BLHA Bucks: play-money bets on matchups you're not in",
                                        guild_only=True)
        awards_group = app_commands.Group(name="awards", description="The annual Awards Ballot (5-3-1)", guild_only=True)
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

        @pool_group.command(name="boxes", description="The Playoff Pool boxes and the pick deadline")
        @app_commands.describe(ephemeral="Only you see the boxes")
        async def pool_boxes(interaction: discord.Interaction, ephemeral: bool = True) -> None:
            await interaction.response.defer(ephemeral=ephemeral, thinking=True)
            boxes = await bot.pool_boxes_or_reply(interaction)
            if boxes is not None:
                embed = pool_view.boxes_embed(boxes, await bot.pool_entries_via())
                await interaction.followup.send(embed=discord.Embed.from_dict(embed), ephemeral=ephemeral)

        @pool_group.command(name="pick", description="Pick or change your franchise's Playoff Pool players")
        async def pool_pick(interaction: discord.Interaction) -> None:
            f, why = bot.member_team(interaction.user)
            if f is None:
                await interaction.response.send_message(why, ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            if await bot.pool_entries_via() != pool_view.BOT:
                await interaction.followup.send(pool_view.DM_ENTRIES, ephemeral=True)
                return
            boxes = await bot.pool_boxes_or_reply(interaction)
            if boxes is None:
                return
            if boxes.locked(utcnow()):
                await interaction.followup.send(
                    f"Playoff Pool picks locked at the first puck drop, {embeds.stamp(boxes.deadline)}.",
                    ephemeral=True)
                return
            view = PoolPicksView(bot, boxes, f.name)
            await interaction.followup.send(view.content(), view=view, ephemeral=True)

        @pool_group.command(name="export",
                            description="Commissioner, after the deadline: the Playoff Pool picks as entries.yaml")
        async def pool_export(interaction: discord.Interaction) -> None:
            if not bot.is_commissioner(interaction.user):
                await interaction.response.send_message("Only the Commissioner can export the pool entries.",
                                                        ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            if await bot.pool_entries_via() != pool_view.BOT:
                await interaction.followup.send(pool_view.DM_EXPORT, ephemeral=True)
                return
            # A fresh read: the cached boxes may predate the published deadline.
            boxes = await bot.pool_boxes_or_reply(interaction, pool_view.RECHECK_SECONDS)
            if boxes is None:
                return
            now = utcnow()
            refusal = pool_view.export_refusal(boxes, now)
            if refusal:
                await interaction.followup.send(refusal, ephemeral=True)
                return
            rows = bot.store.pool_entries(boxes.year, deadline=boxes.deadline)
            late = bot.store.pool_late_picks(boxes.year, boxes.deadline)
            text = pool_view.export_text(boxes, rows)
            bot.store.log(interaction.user.id, "pool_export",
                          {"year": boxes.year, "entries": len(rows), "late_picks": len(late)}, now=now)
            await interaction.followup.send(pool_view.export_note(boxes, rows, late), ephemeral=True,
                                            file=discord.File(io.BytesIO(text.encode("utf-8")),
                                                              filename="entries.yaml"))

        # -- BLHA Bucks: /book ------------------------------------------------
        open_book_week = bot.open_book_week

        @book_group.command(name="lines", description="This Week's BLHA Bucks lines (play money)")
        async def book_lines(interaction: discord.Interaction) -> None:
            row = bot.store.latest_book_week()
            if row is None:
                await interaction.response.send_message(
                    "No BLHA Bucks lines have been posted yet. They post when the previous Week is final.",
                    ephemeral=True)
                return
            locks = parse(row["locks_at"])
            number = int(row["period"])
            if row["status"] == "settled":
                state = f"Week {number} is settled; the next lines post when the current Week is final."
            elif row["status"] != "open" or pickem.is_locked(locks, utcnow()):
                state = f"Week {number} bets are locked while the Week is played."
            else:
                state = f"Week {number} is open for bets with `/book bet`."
            embed = book.lines_embed(number, bot.book_lines_of(row), locks, pickem.season_label(row["season"]))
            await interaction.response.send_message(state, embed=discord.Embed.from_dict(embed), ephemeral=True)

        @book_group.command(name="bet", description="Bet BLHA Bucks on a matchup your franchise isn't in (0 removes a bet)")
        @app_commands.describe(matchup="A matchup on this Week's board (never your own)",
                               side="The team you're backing, with its spread",
                               amount="Bucks on this bet; 100 a Week in all, unused Bucks don't carry over. 0 removes it")
        async def book_bet(interaction: discord.Interaction, matchup: str, side: str,
                           amount: app_commands.Range[int, 0, 100]) -> None:
            f, why = bot.book_player(interaction.user)
            if f is None:
                await interaction.response.send_message(why, ephemeral=True)
                return
            row, lines = open_book_week()
            if row is None:
                await interaction.response.send_message(
                    "No Week is open for bets right now. Lines post when the previous Week is final, and bets lock "
                    "when the Week starts.", ephemeral=True)
                return
            key, number, now = row["season"], int(row["period"]), utcnow()
            line = next((x for x in lines if x.key == matchup), None)
            picked = book.side_from(line, side)
            mine = bot.store.user_bets(key, number, interaction.user.id)
            error = book.check_bet(line, picked or "", int(amount), f.fantrax_team_id,
                                   book.staked(mine, except_matchup=matchup), locked=False)
            if not error and not amount and line.key not in mine:
                error = "You have no bet on that matchup to remove."
            if error:
                await interaction.response.send_message(error, ephemeral=True)
                return
            bot.store.place_bet(key, number, interaction.user.id, line.key, picked, int(amount), f.name, now=now)
            mine = bot.store.user_bets(key, number, interaction.user.id)
            done = (f"Removed your bet on {line.away} at {line.home}." if not amount
                    else f"**{amount} Bucks** on **{line.label(picked)}**. Play money only.")
            text = book.mybets_text(number, lines, mine, parse(row["locks_at"]), locked=False)
            await interaction.response.send_message(f"{done}\n{text}", ephemeral=True)

        @book_bet.autocomplete("matchup")
        async def book_bet_matchup(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
            return bot.book_matchup_choices(interaction.user, current)

        @book_bet.autocomplete("side")
        async def book_bet_side(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
            return bot.book_side_choices(str(getattr(interaction.namespace, "matchup", "") or ""))

        @book_group.command(name="mybets", description="Your BLHA Bucks bets this Week and your season profit (private)")
        async def book_mybets(interaction: discord.Interaction) -> None:
            f, why = bot.book_player(interaction.user)
            if f is None:
                await interaction.response.send_message(why, ephemeral=True)
                return
            row = bot.store.latest_book_week()
            if row is None:
                await interaction.response.send_message("No BLHA Bucks Week has been posted yet.", ephemeral=True)
                return
            key, number = row["season"], int(row["period"])
            locks = parse(row["locks_at"])
            found = json.loads(row["results"] or "{}") if row["status"] == "settled" else None
            text = book.mybets_text(number, bot.book_lines_of(row), bot.store.user_bets(key, number, interaction.user.id),
                                    locks, locked=row["status"] != "open" or pickem.is_locked(locks, utcnow()),
                                    found=found)
            board, _ = bot.book_board(key)
            mine = next(((rank, r) for rank, r in book.ranked(board) if r.user_id == interaction.user.id), None)
            if mine is None:
                text += "\nSeason profit: no settled bets yet."
            else:
                rank, r = mine
                text += (f"\nSeason profit: **{book.signed(r.profit)} Bucks** ({r.record}), "
                         f"rank {rank} of {len(board)}.")
            await interaction.response.send_message(text, ephemeral=True)

        @book_group.command(name="leaderboard", description="BLHA Bucks season profit standings")
        async def book_leaderboard(interaction: discord.Interaction) -> None:
            key = bot.store.latest_book_season()
            if key is None:
                embed = book.leaderboard_embed([], "This Season", 0)
            else:
                board, weeks = bot.book_board(key)
                embed = book.leaderboard_embed(board, pickem.season_label(key), weeks)
            await interaction.response.send_message(embed=discord.Embed.from_dict(embed))

        # -- Awards Ballot: /awards -------------------------------------------
        listed = [app_commands.Choice(name=a.name, value=a.key) for a in awards.AWARDS if a.listed]

        @awards_group.command(name="open", description="Commissioner: open the Awards Ballot. No self-nominations; "
                                                       "your ballot counts the same (19.3)")
        @app_commands.describe(
            season="The Season being honored, e.g. 2027",
            trades="Trade of the Year: Franchise 3 + Franchise 7: what moved; separate trades with ;",
            waivers="Waiver Steal of the Year: Franchise 3: the player; separate nominees with ;",
            comebacks="Comeback Franchise (blank: biggest climbs since last Season): franchise names, with ;",
            busts="Bust of the Year (blank: biggest falls since last Season): Franchise 3: player, with ;",
            deadline="When ballots close, e.g. 2028-04-20 (end of day, league time). Blank: awards.ballot_days")
        async def awards_open(interaction: discord.Interaction, season: int, trades: str = "", waivers: str = "",
                              comebacks: str = "", busts: str = "", deadline: str = "") -> None:
            if not bot.is_commissioner(interaction.user):
                await interaction.response.send_message("Only the Commissioner opens the Awards Ballot.", ephemeral=True)
                return
            if bot.store.awards_season(season) is not None:
                await interaction.response.send_message(f"Season {season}'s Awards Ballot was already opened.",
                                                        ephemeral=True)
                return
            now = utcnow()
            closes = now + timedelta(days=bot.cfg.awards_ballot_days)
            if deadline.strip():
                closes, error = awards.parse_deadline(deadline, now, bot.cfg.timezone)
                if error:
                    await interaction.response.send_message(error, ephemeral=True)
                    return
            await interaction.response.defer(ephemeral=True, thinking=True)
            notes: list[str] = []
            phase = await asyncio.to_thread(bot.league_phase)
            if phase is None:
                notes.append("Fantrax couldn't be read, so the bot couldn't confirm the Championship is over.")
            problems = awards.open_problems(phase, season)
            if problems:
                await interaction.followup.send("Can't open the Awards Ballot:\n- " + "\n- ".join(problems),
                                                ephemeral=True)
                return
            current = await asyncio.to_thread(bot.final_ranks)
            if current:
                bot.store.save_ranks(season, current, now=now)
            elif not (comebacks.strip() and busts.strip()):
                notes.append("Couldn't read the Fantrax standings, so Comeback and Bust can't be proposed from them.")
            nominees, errors, more = awards.build_ballot(
                bot.franchises(), {"trade": trades, "waiver": waivers, "comeback": comebacks, "bust": busts},
                bot.store.ranks(season - 1), current, bot.nominator_franchises(interaction.user, commissioner=True))
            if errors:
                await interaction.followup.send("Fix these and run `/awards open` again:\n- " + "\n- ".join(errors),
                                                ephemeral=True)
                return
            channel = await bot.channel(bot.cfg.awards_ballot_channel_id or bot.cfg.voting_channel_id)
            if channel is None:
                await interaction.followup.send("Set discord.awards_ballot_channel_id (or voting_channel_id) first.",
                                                ephemeral=True)
                return
            msg = await channel.send(embed=discord.Embed.from_dict(awards.ballot_embed(season, nominees, closes)),
                                     view=AwardsPostView(bot))
            bot.store.open_awards(season, awards.nominees_to_json(nominees), user_id=interaction.user.id, now=now,
                                  closes_at=closes)
            bot.store.set_awards_message(season, msg.channel.id, msg.id)
            extra = "".join(f"\n- {n}" for n in notes + more)
            await interaction.followup.send(f"Season {season} Awards Ballot is open: {msg.jump_url}{extra}",
                                            ephemeral=True)

        @awards_group.command(name="nominate", description="Commissioner or Assistant: add a nominee. Never your own "
                                                           "franchise (19.3)")
        @app_commands.describe(award="The award", nominee="Franchise 3: what they did (a trade: Franchise 3 + "
                                                          "Franchise 7: what moved)")
        @app_commands.choices(award=listed)
        async def awards_nominate(interaction: discord.Interaction, award: app_commands.Choice[str],
                                  nominee: str) -> None:
            is_commissioner = bot.is_commissioner(interaction.user)
            if not (is_commissioner or bot.is_assistant(interaction.user)):
                await interaction.response.send_message(
                    "Only the Commissioner or an Assistant Commissioner adds nominees.", ephemeral=True)
                return
            row = bot.store.latest_awards()
            now = utcnow()
            if row is None or row["status"] != "open" or now >= parse(row["closes_at"]):
                await interaction.response.send_message("No Awards Ballot is open.", ephemeral=True)
                return
            kind = awards.BY_KEY[award.value]
            nominees = awards.nominees_from_json(row["nominees"])
            existing = nominees.get(kind.key, [])
            found, bad = awards.parse_nominees(kind, nominee, [f.name for f in bot.cfg.franchises],
                                               start=awards.next_index(existing))
            nominator = bot.nominator_franchises(interaction.user, commissioner=is_commissioner)
            problems = bad + awards.nomination_problems(kind, found, nominator, commissioner=is_commissioner)
            if not found and not problems:
                problems = ["Type a nominee, e.g. Franchise 3: Quinn Hughes off waivers."]
            nominees[kind.key] = existing + found
            problems += awards.too_many(nominees)
            if problems:
                await interaction.response.send_message("Not added:\n- " + "\n- ".join(problems), ephemeral=True)
                return
            bot.store.set_awards_nominees(int(row["season"]), awards.nominees_to_json(nominees),
                                          user_id=interaction.user.id, now=now,
                                          detail={"award": kind.key, "nominees": [n.as_dict() for n in found]})
            note = ""
            try:  # keep the public ballot post's nominee list current
                channel = await bot.channel(int(row["channel_id"]))
                message = await channel.fetch_message(int(row["message_id"]))
                embed = awards.ballot_embed(int(row["season"]), nominees, parse(row["closes_at"]))
                await message.edit(embed=discord.Embed.from_dict(embed))
            except Exception as exc:
                log.warning("Could not update the Awards Ballot post: %s", exc)
                note = " (The ballot post couldn't be updated, but the nominee is on every ballot.)"
            await interaction.response.send_message(
                f"Added to {kind.name}: " + "; ".join(n.label for n in found) + "." + note, ephemeral=True)

        @awards_group.command(name="close", description="Commissioner: close the Awards Ballot now")
        async def awards_close(interaction: discord.Interaction) -> None:
            if not bot.is_commissioner(interaction.user):
                await interaction.response.send_message("Only the Commissioner closes the Awards Ballot.", ephemeral=True)
                return
            row = bot.store.latest_awards()
            if row is None or row["status"] != "open":
                await interaction.response.send_message("No Awards Ballot is open.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            await bot.close_awards_ballot(row, utcnow(), interaction.user.id)
            await interaction.followup.send(f"Season {row['season']} Awards ballots are closed. Post the winners with "
                                            "`/awards results`.", ephemeral=True)

        @awards_group.command(name="results", description="Commissioner: post the Awards winners and save the JSON export")
        @app_commands.describe(again="Post them again even though they were already posted")
        async def awards_results(interaction: discord.Interaction, again: bool = False) -> None:
            if not bot.is_commissioner(interaction.user):
                await interaction.response.send_message("Only the Commissioner posts the Awards results.", ephemeral=True)
                return
            row = bot.store.latest_awards()
            if row is None:
                await interaction.response.send_message("No Awards Ballot has been opened.", ephemeral=True)
                return
            year = int(row["season"])
            if row["status"] == "open":
                await interaction.response.send_message(
                    "Ballots are still open. Close them with `/awards close` or wait for the deadline.", ephemeral=True)
                return
            if row["status"] == "posted" and not again:
                await interaction.response.send_message(
                    f"Season {year}'s winners were already posted. Use `again: True` to post them again.",
                    ephemeral=True)
                return
            channel = await bot.channel(bot.cfg.hall_of_champions_channel_id)
            if channel is None:
                await interaction.response.send_message("Set discord.hall_of_champions_channel_id first.",
                                                        ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            nominees = awards.nominees_from_json(row["nominees"])
            ballots = bot.store.awards_ballots(year)
            voters = bot.awards_voters()
            results = awards.tally_all(nominees, ballots, voters)
            got = awards.returned(ballots, voters)
            payload = awards.season_payload(year, results, closed_at=parse(row["closed_at"]), ballots=len(got),
                                            eligible=len(voters), franchises=bot.cfg.franchises)
            msg = await channel.send(embed=discord.Embed.from_dict(
                awards.results_embed(year, results, len(got), len(voters))))
            now = utcnow()
            bot.store.set_awards_results(year, payload, now=now, user_id=interaction.user.id)
            path = Path(bot.cfg.awards_export_path) if bot.cfg.awards_export_path else awards.default_export_path()
            try:
                export = await asyncio.to_thread(awards.write_export, path, payload, now)
                saved = f"Saved to `{path}`."
            except OSError as exc:
                log.warning("Could not write the awards export %s: %s", path, exc)
                export = awards.merge_export(None, payload, now)
                saved = f"Couldn't write `{path}` ({exc.strerror or exc}); the attached file has the same data."
            data = json.dumps(export, indent=2, ensure_ascii=False).encode("utf-8")
            await interaction.followup.send(
                f"Winners posted: {msg.jump_url}\n{saved} The attached JSON is the trophy-case export for the history "
                "site (format in bot/README.md).",
                file=discord.File(io.BytesIO(data), filename="blha_awards.json"), ephemeral=True)

        @awards_group.command(name="status", description="Which franchises have returned an Awards ballot (not how)")
        async def awards_status(interaction: discord.Interaction) -> None:
            row = bot.store.latest_awards()
            if row is None:
                await interaction.response.send_message("No Awards Ballot has been opened.", ephemeral=True)
                return
            voters = bot.awards_voters()
            done = awards.returned(bot.store.awards_ballots(int(row["season"])), voters)
            waiting = [v for v in voters if v not in done]
            await interaction.response.send_message(
                awards.status_text(int(row["season"]), row["status"], parse(row["closes_at"]), done, waiting),
                ephemeral=True)

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

        for group in (proposal, vote, franchise, panel, pickem_group, pool_group, book_group, awards_group):
            self.tree.add_command(group)
        for command in (rule, deadlines_cmd, minor_cmd, myteam, tradecheck):
            self.tree.add_command(command)
