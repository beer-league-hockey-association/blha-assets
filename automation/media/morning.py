#!/usr/bin/env python3
"""BLHA Morning Skate: last night's NHL games in 📸│media, every morning.

The scheduler starts this once a day (08:30 ET, all year). For the previous
night's NHL date it posts, once:

  1. LAST NIGHT IN THE NHL: one line per final game (winner in bold, OT/SO
     marked) with links to the NHL.com recap and condensed game.
  2. THE BLHA GOAL REEL (only when a player on a BLHA roster scored or
     assisted): one field per BLHA franchise listing its players' goals, each
     with a link to the NHL.com clip, and assists.
  3. Up to ``max_youtube`` plain messages, each just one NHL YouTube highlight
     URL, so Discord shows the playable video. Games are ranked by BLHA
     goals + assists, then OT/SO, then total goals.

Nights without a final regular-season or playoff game post nothing. Links
only: nothing is downloaded or re-uploaded.

Data (all read-only):
  - NHL score API: https://api-web.nhle.com/v1/score/YYYY-MM-DD (games, links,
    goals with clip links and assists).
  - NHL YouTube channel feed (Atom): per-game videos titled like
    "Oilers vs. Ducks | NHL Highlights | Oct 7, 2026". Shorts are ignored.
  - Fantrax getTeamRosters + getPlayerIds for BLHA ownership. Players are
    matched with the Wire's roster matching (wire/roster.py): name, narrowed
    by NHL team; a name that could be two players is skipped.

State (state/morning_skate.json, kept on the automation-state branch) is keyed
by NHL date and records each part as it is posted, so a re-run never posts a
part twice and a failed part is retried on the next run.

Modes:
  preview  print the messages; no Discord, no state change
  test     post [TEST] copies; no state change
  live     post the night's messages once and record them
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
AUTOMATION = ROOT.parent
for folder in (AUTOMATION, AUTOMATION / "wire"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import roster  # noqa: E402  (wire/roster.py)
from blha.fantrax import Fantrax  # noqa: E402
from blha.league import AVATAR, DEFAULT_LEAGUE_NAME, color_value, load_json, load_league, save_json, timezone_of  # noqa: E402
from discord_webhook import send_discord_webhook  # noqa: E402

STATE_PATH = ROOT / "state" / "morning_skate.json"
DEFAULT_WEBHOOK = "BLHA_WEBHOOK_MEDIA"
DEFAULT_POST_TIME = "08:30"
DEFAULT_MAX_YOUTUBE = 3
MAX_YOUTUBE_CAP = 10
KEEP_DATES = 60

SCORE_URL = "https://api-web.nhle.com/v1/score/{date}"
NHL_SITE = "https://www.nhl.com"
YOUTUBE_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id=UCqFMzb-4AUf6WAIbl132QKA"
USER_AGENT = "BLHA-Morning-Skate/1.0 (+https://github.com/beer-league-hockey-association/blha-assets)"

# The 📸│media channel's existing identity (the Wire's podcast posts).
USERNAME = "BLHA News Wire"
FOOTER = "MORNING SKATE"
SCORE_SOURCE = "NHL DATA"
REEL_SOURCE = "NHL AND FANTRAX DATA"

FINAL_STATES = {"OFF", "FINAL"}
COUNTED_GAME_TYPES = {2, 3}  # regular season, playoffs
SKIPPED_SCHEDULE_STATES = {"PPD", "CNCL", "SUSP"}

# Discord limits, with a little headroom.
DESCRIPTION_LIMIT = 4096
DESCRIPTION_BUDGET = 4000
EMBED_TOTAL_LIMIT = 6000
MESSAGE_BUDGET = 5800
FIELD_LIMIT = 1024
MAX_FIELDS = 25
MAX_EMBEDS = 10

ATOM = "{http://www.w3.org/2005/Atom}"
YT = "{http://www.youtube.com/xml/schemas/2015}"
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{6,20}$")

# Team names in YouTube titles -> NHL abbreviations (the score API's codes).
TEAM_NAMES = {
    "ANA": ("ducks", "anaheim", "anaheim ducks"),
    "BOS": ("bruins", "boston", "boston bruins"),
    "BUF": ("sabres", "buffalo", "buffalo sabres"),
    "CGY": ("flames", "calgary", "calgary flames"),
    "CAR": ("hurricanes", "carolina", "carolina hurricanes"),
    "CHI": ("blackhawks", "chicago", "chicago blackhawks"),
    "COL": ("avalanche", "colorado", "colorado avalanche"),
    "CBJ": ("blue jackets", "columbus", "columbus blue jackets"),
    "DAL": ("stars", "dallas", "dallas stars"),
    "DET": ("red wings", "detroit", "detroit red wings"),
    "EDM": ("oilers", "edmonton", "edmonton oilers"),
    "FLA": ("panthers", "florida", "florida panthers"),
    "LAK": ("kings", "los angeles", "los angeles kings"),
    "MIN": ("wild", "minnesota", "minnesota wild"),
    "MTL": ("canadiens", "montreal", "montreal canadiens", "habs"),
    "NSH": ("predators", "nashville", "nashville predators"),
    "NJD": ("devils", "new jersey", "new jersey devils"),
    "NYI": ("islanders", "new york islanders"),
    "NYR": ("rangers", "new york rangers"),
    "OTT": ("senators", "ottawa", "ottawa senators"),
    "PHI": ("flyers", "philadelphia", "philadelphia flyers"),
    "PIT": ("penguins", "pittsburgh", "pittsburgh penguins"),
    "SJS": ("sharks", "san jose", "san jose sharks"),
    "SEA": ("kraken", "seattle", "seattle kraken"),
    "STL": ("blues", "st louis", "st louis blues"),
    "TBL": ("lightning", "tampa bay", "tampa bay lightning"),
    "TOR": ("maple leafs", "toronto", "toronto maple leafs"),
    "UTA": ("mammoth", "utah", "utah mammoth", "utah hockey club", "hockey club"),
    "VAN": ("canucks", "vancouver", "vancouver canucks"),
    "VGK": ("golden knights", "vegas", "vegas golden knights"),
    "WSH": ("capitals", "washington", "washington capitals"),
    "WPG": ("jets", "winnipeg", "winnipeg jets"),
}


# --- NHL score data -------------------------------------------------------------

@dataclass
class Person:
    player_id: str
    name: str   # "Connor McDavid"
    last: str   # "McDavid"
    first: str = ""


@dataclass
class Goal:
    team: str
    scorer: Person
    assists: list[Person]
    clip: str = ""


@dataclass
class Game:
    game_id: str
    game_type: int
    away: str
    home: str
    away_score: int
    home_score: int
    outcome: str = ""      # "", "OT", "2OT", "SO"
    recap: str = ""
    condensed: str = ""
    start: str = ""
    goals: list[Goal] = field(default_factory=list)
    names: dict[str, list[str]] = field(default_factory=dict)  # team names from the API

    @property
    def total_goals(self) -> int:
        return self.away_score + self.home_score

    @property
    def label(self) -> str:
        return f"{self.away} at {self.home}"


def _text(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("default")
    return str(value or "").strip()


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _abbrev(team: Any) -> str:
    return _text(team.get("abbrev") if isinstance(team, dict) else "").upper()


def nhl_url(value: Any) -> str:
    """Absolute NHL.com link from a site path ("/video/...") or full URL."""
    text = _text(value)
    if not text:
        return ""
    if text.startswith("https://"):
        return text
    if text.startswith("http://"):
        return "https://" + text[len("http://"):]
    if text.startswith("/"):
        return NHL_SITE + text
    return ""


def outcome_label(raw: dict[str, Any]) -> str:
    outcome = raw.get("gameOutcome") if isinstance(raw.get("gameOutcome"), dict) else {}
    period = raw.get("periodDescriptor") if isinstance(raw.get("periodDescriptor"), dict) else {}
    last = str(outcome.get("lastPeriodType") or period.get("periodType") or "").upper()
    if last == "SO":
        return "SO"
    if last == "OT":
        extra = _int(outcome.get("otPeriods"))
        if extra <= 0:
            number = _int(period.get("number"))
            extra = number - 3 if number > 3 else 1
        return "OT" if extra <= 1 else f"{extra}OT"
    return ""


def _person(raw: Any) -> Person | None:
    if not isinstance(raw, dict):
        return None
    first, last = _text(raw.get("firstName")), _text(raw.get("lastName"))
    name = f"{first} {last}" if first and last else _text(raw.get("name"))
    if not name:
        return None
    return Person(str(raw.get("playerId") or ""), name, last or name.split()[-1], first)


def _shootout(goal: dict[str, Any], game_outcome: str, game_type: int) -> bool:
    period = goal.get("periodDescriptor") if isinstance(goal.get("periodDescriptor"), dict) else {}
    if str(period.get("periodType") or "").upper() == "SO":
        return True
    number = _int(goal.get("period"), _int(period.get("number")))
    return game_outcome == "SO" and game_type == 2 and number >= 5


def _team_names(team: Any) -> list[str]:
    if not isinstance(team, dict):
        return []
    names = [_text(team.get(key)) for key in ("name", "commonName", "placeName")]
    return [n for n in names if n]


def parse_scores(raw: Any, day: date) -> list[Game]:
    """Final regular-season and playoff games for ``day``, in start order.

    Raises ValueError when the response no longer has a ``games`` list, so an
    API change is noticed instead of looking like a night without games.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("games"), list):
        raise ValueError("NHL score response has no games list (API changed?)")
    current = str(raw.get("currentDate") or "")
    if current and current != day.isoformat():
        return []  # the API answered for a different day
    games: list[Game] = []
    for item in raw["games"]:
        if not isinstance(item, dict):
            continue
        if str(item.get("gameState") or "").upper() not in FINAL_STATES:
            continue
        if str(item.get("gameScheduleState") or "").upper() in SKIPPED_SCHEDULE_STATES:
            continue
        game_type = _int(item.get("gameType"))
        if game_type and game_type not in COUNTED_GAME_TYPES:
            continue
        if item.get("gameDate") and str(item["gameDate"])[:10] != day.isoformat():
            continue
        away_raw, home_raw = item.get("awayTeam") or {}, item.get("homeTeam") or {}
        away, home = _abbrev(away_raw), _abbrev(home_raw)
        if not (away and home):
            continue
        outcome = outcome_label(item)
        game = Game(
            game_id=str(item.get("id") or f"{day.isoformat()}-{away}-{home}"),
            game_type=game_type,
            away=away,
            home=home,
            away_score=_int(away_raw.get("score")),
            home_score=_int(home_raw.get("score")),
            outcome=outcome,
            recap=nhl_url(item.get("threeMinRecap")),
            condensed=nhl_url(item.get("condensedGame")),
            start=str(item.get("startTimeUTC") or ""),
            names={away: _team_names(away_raw), home: _team_names(home_raw)},
        )
        for raw_goal in item.get("goals") or []:
            if not isinstance(raw_goal, dict) or _shootout(raw_goal, outcome, game_type):
                continue
            scorer = _person(raw_goal)
            if scorer is None:
                continue
            clip = _text(raw_goal.get("highlightClipSharingUrl"))
            game.goals.append(Goal(
                team=_text(raw_goal.get("teamAbbrev")).upper(),
                scorer=scorer,
                assists=[p for p in (_person(a) for a in raw_goal.get("assists") or []) if p],
                clip=clip if clip.startswith("https://") else "",
            ))
        games.append(game)
    games.sort(key=lambda g: (g.start, g.game_id))
    return games


def unfinished(raw: Any) -> int:
    """Counted games on the night that are neither final nor postponed."""
    count = 0
    for item in (raw.get("games") or []) if isinstance(raw, dict) else []:
        if not isinstance(item, dict):
            continue
        if str(item.get("gameState") or "").upper() in FINAL_STATES:
            continue
        if str(item.get("gameScheduleState") or "").upper() in SKIPPED_SCHEDULE_STATES:
            continue
        if _int(item.get("gameType")) in (0, *COUNTED_GAME_TYPES):
            count += 1
    return count


# --- BLHA rosters and the Goal Reel ---------------------------------------------

@dataclass
class ReelLine:
    name: str
    full: str
    team: str
    clips: list[str] = field(default_factory=list)  # one entry per goal ("" = no clip)
    assists: int = 0

    @property
    def points(self) -> int:
        return len(self.clips) + self.assists


@dataclass
class Franchise:
    name: str
    lines: dict[str, ReelLine] = field(default_factory=dict)

    @property
    def points(self) -> int:
        return sum(line.points for line in self.lines.values())


@dataclass
class Reel:
    franchises: dict[str, Franchise] = field(default_factory=dict)
    by_game: dict[str, int] = field(default_factory=dict)  # BLHA goals + assists per game

    @property
    def empty(self) -> bool:
        return not self.franchises


def load_index(fx: Any) -> roster.RosterIndex | None:
    """BLHA roster index, or None when nobody is rostered or Fantrax fails."""
    try:
        rosters = fx.rosters()
    except Exception as exc:
        print(f"GOAL REEL WARNING: Fantrax roster read failed; no Goal Reel: {exc}")
        return None
    block = rosters.get("rosters") if isinstance(rosters, dict) else None
    if not isinstance(block, dict) or not any(
        (team or {}).get("rosterItems") for team in block.values() if isinstance(team, dict)
    ):
        print("GOAL REEL: no players on BLHA rosters yet; Goal Reel skipped")
        return None
    try:
        players = fx.player_ids()
    except Exception as exc:
        print(f"GOAL REEL WARNING: Fantrax player directory read failed; no Goal Reel: {exc}")
        return None
    index = roster.build_index(rosters, players)
    if index.empty:
        print("GOAL REEL: no rostered players found in the Fantrax player directory; Goal Reel skipped")
        return None
    print(f"GOAL REEL: {len(index.rostered_names)} rostered players indexed")
    return index


def _name_parts(fantrax_name: str) -> tuple[str, str]:
    """(first, last), normalized, from Fantrax's "Last, First"."""
    if fantrax_name.count(",") == 1:
        last, first = (part.strip() for part in fantrax_name.split(",", 1))
    else:
        words = fantrax_name.split()
        first, last = (" ".join(words[:-1]), words[-1]) if len(words) > 1 else ("", fantrax_name)
    return roster.normalize_player_name(first), roster.normalize_player_name(last)


class Matcher:
    """The Wire's roster matching, plus one careful fallback for short names.

    The NHL and Fantrax sometimes spell a first name differently ("Mitch" /
    "Mitchell"). Only when no Fantrax player has the NHL's exact name, a
    player is accepted if he is the only one on that NHL team with the same
    last name and a first name starting with the same three letters.
    """

    def __init__(self, index: roster.RosterIndex) -> None:
        self.index = index
        self.by_team_last: dict[tuple[str, str], list[tuple[str, roster.Player]]] = {}
        for players in index.by_name.values():
            for player in players:
                first, last = _name_parts(player.name)
                self.by_team_last.setdefault((player.team, last), []).append((first, player))

    def match(self, person: Person, team: str) -> roster.Player | None:
        player = self.index.match(person.name, team)
        if player is not None or self.index.by_name.get(roster.normalize_player_name(person.name)):
            return player
        first = roster.normalize_player_name(person.first)[:3]
        key = (roster.normalize_team(team), roster.normalize_player_name(person.last))
        if len(first) < 3 or not key[0]:
            return None
        found = [p for f, p in self.by_team_last.get(key, []) if f[:3] == first]
        return found[0] if len(found) == 1 and found[0].owner_id else None


def build_reel(games: list[Game], index: roster.RosterIndex | None) -> Reel:
    reel = Reel()
    if index is None:
        return reel
    matcher = Matcher(index)

    def credit(game: Game, person: Person, team: str) -> ReelLine | None:
        player = matcher.match(person, team)
        if player is None:
            return None
        franchise = reel.franchises.setdefault(player.owner_id, Franchise(player.owner_name))
        line = franchise.lines.setdefault(player.player_id, ReelLine(person.last, person.name, team))
        reel.by_game[game.game_id] = reel.by_game.get(game.game_id, 0) + 1
        return line

    for game in games:
        for goal in game.goals:
            team = goal.team or ""
            line = credit(game, goal.scorer, team)
            if line is not None:
                line.clips.append(goal.clip)
            for helper in goal.assists:
                line = credit(game, helper, team)
                if line is not None:
                    line.assists += 1
    return reel


def _escape(text: str) -> str:
    """Keep names from turning into Discord formatting."""
    return re.sub(r"([*_`~|\\])", r"\\\1", text)


def _link(url: str) -> str:
    return url.replace(")", "%29").replace(" ", "%20")


def reel_line(line: ReelLine, *, full_name: bool = False) -> str:
    parts: list[str] = []
    if line.clips:
        count = len(line.clips)
        label = "goal" if count == 1 else f"{count} goals"
        links = " ".join(f"[▶]({_link(c)})" for c in line.clips if c)
        parts.append(f"{label} {links}".strip())
    if line.assists:
        parts.append("assist" if line.assists == 1 else f"{line.assists} assists")
    who = _escape(line.full if full_name else line.name)
    return f"{who} ({line.team}) — {', '.join(parts)}"


def franchise_value(franchise: Franchise) -> str:
    lines = sorted(franchise.lines.values(), key=lambda l: (-l.points, -len(l.clips), l.full))
    last_names = [(l.name, l.team) for l in lines]
    rows = [reel_line(l, full_name=last_names.count((l.name, l.team)) > 1) for l in lines]
    return clip_text("\n".join(rows), FIELD_LIMIT)


# --- YouTube highlights ---------------------------------------------------------

@dataclass
class Video:
    video_id: str
    title: str
    link: str
    published: str = ""

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"

    @property
    def short(self) -> bool:
        return "/shorts/" in self.link or "#shorts" in self.title.lower()


HIGHLIGHT_TITLE = re.compile(
    r"^\s*(?P<a>[^|]+?)\s+(?:vs\.?|at|@)\s+(?P<b>[^|]+?)\s*\|(?:[^|]*\|)*?\s*NHL Highlights\s*\|\s*(?P<date>[^|]+?)\s*$",
    re.I,
)


def parse_feed(xml_text: str) -> list[Video]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise ValueError(f"YouTube feed is not valid XML: {exc}") from exc
    if root.tag != f"{ATOM}feed":
        raise ValueError("YouTube feed is not an Atom feed (format changed?)")
    videos: list[Video] = []
    for entry in root.findall(f"{ATOM}entry"):
        video_id = (entry.findtext(f"{YT}videoId") or "").strip()
        if not VIDEO_ID.match(video_id):
            continue
        link = ""
        for node in entry.findall(f"{ATOM}link"):
            if node.get("rel", "alternate") == "alternate":
                link = node.get("href", "")
                break
        videos.append(Video(video_id, (entry.findtext(f"{ATOM}title") or "").strip(), link,
                            (entry.findtext(f"{ATOM}published") or "").strip()))
    return videos


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower().replace(".", "")
    return re.sub(r"\s+", " ", text).strip()


def title_date(text: str) -> date | None:
    cleaned = re.sub(r"^sept\b", "sep", _plain(text))
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def team_lookup(games: list[Game]) -> dict[str, str]:
    """Known team names plus the score API's own names (unless two teams share one)."""
    lookup = {name: code for code, names in TEAM_NAMES.items() for name in names}
    extra: dict[str, set[str]] = {}
    for game in games:
        for code, names in game.names.items():
            for name in names:
                extra.setdefault(_plain(name), set()).add(code)
    for name, codes in extra.items():
        if name and len(codes) == 1:
            lookup.setdefault(name, next(iter(codes)))
    return lookup


def team_code(name: str, lookup: dict[str, str]) -> str:
    key = _plain(name)
    if key in lookup:
        return lookup[key]
    # "Toronto Maple Leafs" style: match the longest known nickname at the end.
    for known in sorted(lookup, key=len, reverse=True):
        if key.endswith(" " + known):
            return lookup[known]
    return ""


def highlight_matchup(video: Video, lookup: dict[str, str]) -> tuple[frozenset[str], date] | None:
    """(the two teams, the game date) for a per-game highlight video, else None."""
    if video.short:
        return None
    match = HIGHLIGHT_TITLE.match(video.title)
    if not match:
        return None
    when = title_date(match.group("date"))
    a, b = team_code(match.group("a"), lookup), team_code(match.group("b"), lookup)
    if when is None or not a or not b or a == b:
        return None
    return frozenset((a, b)), when


def rank_highlights(games: list[Game], videos: list[Video], day: date,
                    blha_points: dict[str, int], limit: int) -> list[tuple[Game, Video]]:
    """Highlight videos for the night's games, best first, at most ``limit``.

    Order: BLHA goals + assists in the game, then OT/SO, then total goals,
    then start time.
    """
    lookup = team_lookup(games)
    by_pair: dict[frozenset[str], Video] = {}
    for video in videos:
        found = highlight_matchup(video, lookup)
        if found and found[1] == day:
            by_pair.setdefault(found[0], video)
    picks = [(i, g, by_pair[frozenset((g.away, g.home))]) for i, g in enumerate(games)
             if frozenset((g.away, g.home)) in by_pair]
    picks.sort(key=lambda p: (-blha_points.get(p[1].game_id, 0), 0 if p[1].outcome else 1,
                              -p[1].total_goals, p[0]))
    return [(g, v) for _, g, v in picks[:max(0, limit)]]


# --- Discord payloads -----------------------------------------------------------

def clip_text(text: str, limit: int) -> str:
    """Fit ``text`` in ``limit`` characters, cutting at a line break."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 2].rsplit("\n", 1)[0]
    return cut + "\n…"


def embed_size(embed: dict[str, Any]) -> int:
    size = len(embed.get("title") or "") + len(embed.get("description") or "")
    size += len((embed.get("footer") or {}).get("text") or "")
    size += len((embed.get("author") or {}).get("name") or "")
    for item in embed.get("fields") or []:
        size += len(item.get("name") or "") + len(item.get("value") or "")
    return size


def _message(embeds: list[dict[str, Any]]) -> dict[str, Any]:
    return {"username": USERNAME, "avatar_url": AVATAR, "allowed_mentions": {"parse": []}, "embeds": embeds}


def pack(embeds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group embeds into as few messages as Discord's per-message limits allow."""
    messages: list[list[dict[str, Any]]] = []
    for embed in embeds:
        if messages and len(messages[-1]) < MAX_EMBEDS and \
                sum(embed_size(e) for e in messages[-1]) + embed_size(embed) <= MESSAGE_BUDGET:
            messages[-1].append(embed)
        else:
            messages.append([embed])
    return [_message(group) for group in messages]


def _finish(embeds: list[dict[str, Any]], footer: str, now: datetime) -> list[dict[str, Any]]:
    """Footer and timestamp on the last embed only; '(continued)' titles after the first."""
    for i, embed in enumerate(embeds):
        if i:
            embed["title"] = embed["title"] + " (continued)"
    embeds[-1]["footer"] = {"text": footer}
    embeds[-1]["timestamp"] = now.isoformat()
    return embeds


@dataclass
class Look:
    league_name: str
    season_label: str
    color: int
    test: bool = False

    def title(self, text: str) -> str:
        return ("[TEST] " + text) if self.test else text

    @property
    def header(self) -> str:
        text = f"**{_escape(self.league_name or DEFAULT_LEAGUE_NAME)}**"
        return text + (f" • {self.season_label}" if self.season_label else "")


def game_line(game: Game) -> str:
    if game.away_score >= game.home_score:
        winner, loser = (game.away, game.away_score), (game.home, game.home_score)
    else:
        winner, loser = (game.home, game.home_score), (game.away, game.away_score)
    text = f"**{winner[0]} {winner[1]}**, {loser[0]} {loser[1]}"
    if game.outcome:
        text += f" ({game.outcome})"
    links = [f"[{label}]({_link(url)})" for label, url in (("Recap", game.recap), ("Condensed", game.condensed)) if url]
    return " · ".join([text, *links])


def night_title(day: date) -> str:
    return f"LAST NIGHT IN THE NHL — {day.strftime('%A, %B')} {day.day}"


def summary_messages(look: Look, games: list[Game], day: date, now: datetime) -> list[dict[str, Any]]:
    playoff = all(g.game_type == 3 for g in games)
    noun = "playoff game" if playoff else "game"
    count = len(games)
    note = (f"*{count} {noun}{'' if count == 1 else 's'} final. "
            "Recap and Condensed open the video on NHL.com.*")
    title = look.title(night_title(day))
    chunks: list[list[str]] = [[]]
    used = len(look.header) + len(note) + 2
    for line in (game_line(g) for g in games):
        if chunks[-1] and used + len(line) + 1 > DESCRIPTION_BUDGET:
            chunks.append([])
            used = 0
        chunks[-1].append(line)
        used += len(line) + 1
    embeds = []
    for i, lines in enumerate(chunks):
        body = "\n".join(lines)
        description = f"{look.header}\n{note}\n\n{body}" if i == 0 else body
        embeds.append({"title": title, "description": description[:DESCRIPTION_LIMIT], "color": look.color})
    return pack(_finish(embeds, f"{FOOTER} • {SCORE_SOURCE}", now))


def reel_messages(look: Look, reel: Reel, now: datetime) -> list[dict[str, Any]]:
    if reel.empty:
        return []
    ordered = sorted(reel.franchises.values(), key=lambda f: (-f.points, f.name.lower()))
    fields = [{"name": clip_text(_escape(f.name), 256), "value": franchise_value(f), "inline": False}
              for f in ordered]
    title = look.title("THE BLHA GOAL REEL")
    description = (f"{look.header}\n*Goals and assists last night by players on BLHA rosters. "
                   "▶ opens the goal clip on NHL.com.*")
    footer = f"{FOOTER} • {REEL_SOURCE}"
    reserve = len(title) + len(" (continued)") + len(footer)
    embeds: list[dict[str, Any]] = []
    current: dict[str, Any] = {"title": title, "description": description, "color": look.color, "fields": []}
    for item in fields:
        size = len(item["name"]) + len(item["value"])
        if current["fields"] and (len(current["fields"]) >= MAX_FIELDS
                                  or embed_size(current) + size + reserve > MESSAGE_BUDGET):
            embeds.append(current)
            current = {"title": title, "color": look.color, "fields": []}
        current["fields"].append(item)
    embeds.append(current)
    return pack(_finish(embeds, footer, now))


def video_message(look: Look, video: Video) -> dict[str, Any]:
    """Just the YouTube link, so Discord shows its own playable preview."""
    content = ("[TEST] " if look.test else "") + video.url
    return {"username": USERNAME, "avatar_url": AVATAR, "allowed_mentions": {"parse": []}, "content": content}


# --- Fetching -------------------------------------------------------------------

def http_get(url: str) -> Any:
    import requests

    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    response.raise_for_status()
    return response


def get_json(url: str) -> Any:
    return http_get(url).json()


def get_text(url: str) -> str:
    return http_get(url).text


# --- Run ------------------------------------------------------------------------

def _clock(text: Any, default: str) -> time:
    hour, minute = (int(part) for part in str(text or default).split(":", 1))
    return time(hour, minute)


def _max_youtube(settings: dict[str, Any]) -> int:
    value = _int(settings.get("max_youtube"), DEFAULT_MAX_YOUTUBE)
    return max(0, min(MAX_YOUTUBE_CAP, value))


def _prune(dates: dict[str, Any]) -> dict[str, Any]:
    return {key: dates[key] for key in sorted(dates)[-KEEP_DATES:]}


def run(
    mode: str,
    *,
    now: datetime | None = None,
    league: dict[str, Any] | None = None,
    fx: Any = None,
    fetch_json: Callable[[str], Any] | None = None,
    fetch_text: Callable[[str], str] | None = None,
    night: date | None = None,
) -> int:
    cfg = league or load_league()
    settings = cfg.get("morning_skate") or {}
    tz: ZoneInfo = timezone_of(cfg)
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(tz)
    day = night or (local.date() - timedelta(days=1))
    secret = str(settings.get("webhook") or DEFAULT_WEBHOOK)
    max_youtube = _max_youtube(settings)
    print(f"BLHA MORNING SKATE mode={mode.upper()} nhl_date={day} local_time={local:%Y-%m-%d %H:%M}")

    if mode == "live":
        if not settings.get("enabled", True):
            print("RESULT: morning_skate.enabled is false in league.yaml; nothing posted")
            return 0
        if day >= local.date():
            print(f"RESULT: {day} is not over yet; the Morning Skate covers finished nights only")
            return 0
        post_time = _clock(settings.get("post_time"), DEFAULT_POST_TIME)
        if night is None and local.time() < post_time:
            print(f"RESULT: before {post_time:%H:%M}; nothing to post yet")
            return 0

    state = load_json(STATE_PATH, {}) if mode == "live" else {}
    dates = state.get("dates") if isinstance(state.get("dates"), dict) else {}
    record = dict(dates.get(day.isoformat()) or {})
    if mode == "live" and record.get("complete"):
        print(f"RESULT: the Morning Skate for {day} was already posted")
        return 0

    raw = (fetch_json or get_json)(SCORE_URL.format(date=day.isoformat()))
    games = parse_scores(raw, day)
    pending = unfinished(raw)
    print(f"NHL final_games={len(games)} not_final={pending}")
    if not games:
        print(f"RESULT: no final NHL games on {day}; nothing to post")
        return 0

    fx = fx or Fantrax(str(cfg["league_id"]), user_agent="BLHA-Morning-Skate/1.0", timeout=20)
    index = load_index(fx) if settings.get("include_goal_reel", True) else None
    reel = build_reel(games, index)
    print(f"GOAL REEL franchises={len(reel.franchises)} blha_points={sum(reel.by_game.values())}")
    try:
        league_name = str(fx.league_info().get("leagueName") or "")
    except Exception:
        league_name = ""

    videos: list[Video] = []
    feed_ok = max_youtube == 0
    if max_youtube:
        try:
            videos = parse_feed((fetch_text or get_text)(YOUTUBE_FEED))
            feed_ok = True
        except Exception as exc:
            print(f"YOUTUBE WARNING: highlight feed unavailable: {exc}")
    picks = rank_highlights(games, videos, day, reel.by_game, max_youtube)
    print(f"YOUTUBE feed_entries={len(videos)} highlights_picked={len(picks)}")
    if feed_ok and max_youtube and not picks:
        print(f"YOUTUBE NOTE: no '| NHL Highlights | {day:%b} {day.day}, {day.year}' videos for these games in the feed")
    for rank, (game, video) in enumerate(picks, start=1):
        print(f"HIGHLIGHT {rank}: {game.label} blha={reel.by_game.get(game.game_id, 0)} "
              f"extra={game.outcome or '-'} goals={game.total_goals} {video.url}")

    look = Look(league_name, str(cfg.get("season_label") or ""), color_value(cfg.get("color")), test=(mode == "test"))
    summary = summary_messages(look, games, day, now)
    reel_posts = reel_messages(look, reel, now)
    video_posts = [(video.video_id, video_message(look, video)) for _, video in picks]

    if mode == "preview":
        for body in summary + reel_posts + [b for _, b in video_posts]:
            print(json.dumps(body, indent=2, ensure_ascii=False))
        print(f"RESULT: preview only ({len(summary)} summary, {len(reel_posts)} goal reel, "
              f"{len(video_posts)} highlight messages)")
        return 0

    if mode == "test":
        failed = 0
        for body in summary + reel_posts + [b for _, b in video_posts]:
            ok, detail, _ = send_discord_webhook(secret, body)
            print(f"{'POSTED' if ok else 'ERROR'} test message: {detail}")
            failed += 0 if ok else 1
        return 1 if failed else 0

    # live: post each part once, saving progress after every message.
    def save() -> None:
        dates[day.isoformat()] = record
        state["dates"] = _prune(dates)
        state["updated_at"] = now.isoformat()
        save_json(STATE_PATH, state)

    for part, bodies in (("summary", summary), ("reel", reel_posts)):
        done = _int(record.get(part))
        for i, body in enumerate(bodies):
            if i < done:
                continue
            ok, detail, _ = send_discord_webhook(secret, body)
            if not ok:
                save()
                print(f"ERROR   {part} message {i + 1} of {len(bodies)} not posted: {detail}; retried next run")
                return 1
            record[part] = i + 1
            save()
            print(f"POSTED  {part} message {i + 1} of {len(bodies)}")

    posted = [str(v) for v in record.get("videos") or []]
    for video_id, body in video_posts:
        if video_id in posted:
            continue
        if len(posted) >= max_youtube:
            break
        ok, detail, _ = send_discord_webhook(secret, body)
        if not ok:
            record["videos"] = posted
            save()
            print(f"ERROR   highlight {video_id} not posted: {detail}; retried next run")
            return 1
        posted.append(video_id)
        record["videos"] = posted
        save()
        print(f"POSTED  highlight {body['content']}")

    if not feed_ok:
        record["videos"] = posted
        save()
        print("ERROR   YouTube feed unavailable; highlight videos will be retried next run")
        return 1

    record.update({"videos": posted, "complete": True, "games": len(games), "posted_at": now.isoformat()})
    save()
    print(f"RESULT: Morning Skate for {day} posted")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preview", "test", "live"), default="preview")
    parser.add_argument("--date", default="", help="NHL date YYYY-MM-DD (default: last night)")
    args = parser.parse_args()
    night = None
    if args.date.strip():
        try:
            night = date.fromisoformat(args.date.strip())
        except ValueError:
            print(f"ERROR: --date must be YYYY-MM-DD, got {args.date!r}")
            return 1
    try:
        return run(args.mode, night=night)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
