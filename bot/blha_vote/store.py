"""SQLite storage for proposals, votes, ballots, Pick'em, Playoff Pool picks, BLHA Bucks, the Awards Ballot and the audit trail.

On Railway the database lives on a volume (BLHA_DB_PATH, default
/data/blha_votes.db) so votes survive restarts and redeploys.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    affected_rule TEXT NOT NULL,
    replacement TEXT NOT NULL,
    effective_season INTEGER,
    kind TEXT NOT NULL DEFAULT 'amendment',
    proposed_by TEXT NOT NULL,
    proposer_user_id INTEGER NOT NULL,
    posted_at TEXT NOT NULL,
    channel_id INTEGER,
    message_id INTEGER,
    status TEXT NOT NULL DEFAULT 'discussion'
);
CREATE TABLE IF NOT EXISTS votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    question TEXT NOT NULL,
    options TEXT NOT NULL,
    proposal_id INTEGER REFERENCES proposals(id),
    effective TEXT,
    opened_by INTEGER NOT NULL,
    opened_at TEXT NOT NULL,
    closes_at TEXT NOT NULL,
    channel_id INTEGER,
    message_id INTEGER,
    status TEXT NOT NULL DEFAULT 'open',
    reminded INTEGER NOT NULL DEFAULT 0,
    result TEXT
);
CREATE TABLE IF NOT EXISTS ballots (
    vote_id INTEGER NOT NULL REFERENCES votes(id),
    franchise TEXT NOT NULL,
    choice TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    cast_at TEXT NOT NULL,
    PRIMARY KEY (vote_id, franchise)
);
CREATE TABLE IF NOT EXISTS orphaned (
    franchise TEXT PRIMARY KEY,
    since TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    user_id INTEGER,
    action TEXT NOT NULL,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS pickem_weeks (
    season TEXT NOT NULL,
    period INTEGER NOT NULL,
    matchups TEXT NOT NULL,
    locks_at TEXT NOT NULL,
    posted_at TEXT NOT NULL,
    channel_id INTEGER,
    message_id INTEGER,
    status TEXT NOT NULL DEFAULT 'open',
    winners TEXT,
    scored_at TEXT,
    PRIMARY KEY (season, period)
);
CREATE TABLE IF NOT EXISTS pickem_picks (
    season TEXT NOT NULL,
    period INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    matchup TEXT NOT NULL,
    team_id TEXT NOT NULL,
    picked_at TEXT NOT NULL,
    PRIMARY KEY (season, period, user_id, matchup)
);
CREATE TABLE IF NOT EXISTS pool_picks (
    year INTEGER NOT NULL,
    franchise TEXT NOT NULL,
    box INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    picked_at TEXT NOT NULL,
    PRIMARY KEY (year, franchise, box)
);
CREATE TABLE IF NOT EXISTS pool_entries (
    year INTEGER NOT NULL,
    franchise TEXT NOT NULL,
    completed_at TEXT,
    PRIMARY KEY (year, franchise)
);
CREATE TABLE IF NOT EXISTS book_weeks (
    season TEXT NOT NULL,
    period INTEGER NOT NULL,
    lines TEXT NOT NULL,
    locks_at TEXT NOT NULL,
    posted_at TEXT NOT NULL,
    channel_id INTEGER,
    message_id INTEGER,
    status TEXT NOT NULL DEFAULT 'open',
    results TEXT,
    settled_at TEXT,
    PRIMARY KEY (season, period)
);
CREATE TABLE IF NOT EXISTS book_bets (
    season TEXT NOT NULL,
    period INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    matchup TEXT NOT NULL,
    side TEXT NOT NULL,
    amount INTEGER NOT NULL,
    franchise TEXT NOT NULL,
    placed_at TEXT NOT NULL,
    PRIMARY KEY (season, period, user_id, matchup)
);
CREATE TABLE IF NOT EXISTS book_champions (
    season TEXT PRIMARY KEY,
    user_ids TEXT NOT NULL,
    awarded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS awards_seasons (
    season INTEGER PRIMARY KEY,
    nominees TEXT NOT NULL,
    opened_by INTEGER NOT NULL,
    opened_at TEXT NOT NULL,
    closes_at TEXT NOT NULL,
    channel_id INTEGER,
    message_id INTEGER,
    status TEXT NOT NULL DEFAULT 'open',
    closed_at TEXT,
    results TEXT,
    posted_at TEXT
);
CREATE TABLE IF NOT EXISTS awards_votes (
    season INTEGER NOT NULL,
    franchise TEXT NOT NULL,
    award TEXT NOT NULL,
    place INTEGER NOT NULL,
    nominee TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    cast_at TEXT NOT NULL,
    PRIMARY KEY (season, franchise, award, place)
);
CREATE TABLE IF NOT EXISTS season_ranks (
    season INTEGER PRIMARY KEY,
    ranks TEXT NOT NULL,
    saved_at TEXT NOT NULL
);
"""


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


class Store:
    def __init__(self, path: str | Path) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    # -- audit -------------------------------------------------------------
    def log(self, user_id: int | None, action: str, detail: Any = None, *, now: datetime) -> None:
        self.db.execute("INSERT INTO audit (at, user_id, action, detail) VALUES (?, ?, ?, ?)",
                        (iso(now), user_id, action, json.dumps(detail) if detail is not None else None))
        self.db.commit()

    def audit(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM audit ORDER BY id").fetchall()

    # -- proposals ---------------------------------------------------------
    def add_proposal(self, *, title: str, affected_rule: str, replacement: str, effective_season: int | None,
                     kind: str, proposed_by: str, user_id: int, now: datetime) -> int:
        cur = self.db.execute(
            "INSERT INTO proposals (title, affected_rule, replacement, effective_season, kind, proposed_by, "
            "proposer_user_id, posted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (title, affected_rule, replacement, effective_season, kind, proposed_by, user_id, iso(now)))
        self.db.commit()
        self.log(user_id, "proposal_posted", {"id": cur.lastrowid, "title": title}, now=now)
        return int(cur.lastrowid)

    def set_proposal_message(self, proposal_id: int, channel_id: int, message_id: int) -> None:
        self.db.execute("UPDATE proposals SET channel_id=?, message_id=? WHERE id=?", (channel_id, message_id, proposal_id))
        self.db.commit()

    def proposal(self, proposal_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()

    def set_proposal_status(self, proposal_id: int, status: str) -> None:
        self.db.execute("UPDATE proposals SET status=? WHERE id=?", (status, proposal_id))
        self.db.commit()

    def proposals(self, status: str | None = None) -> list[sqlite3.Row]:
        if status:
            return self.db.execute("SELECT * FROM proposals WHERE status=? ORDER BY id", (status,)).fetchall()
        return self.db.execute("SELECT * FROM proposals ORDER BY id").fetchall()

    # -- votes -------------------------------------------------------------
    def open_vote(self, *, kind: str, title: str, question: str, options: list[str], proposal_id: int | None,
                  effective: str | None, user_id: int, now: datetime, closes_at: datetime) -> int:
        cur = self.db.execute(
            "INSERT INTO votes (kind, title, question, options, proposal_id, effective, opened_by, opened_at, closes_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (kind, title, question, json.dumps(options), proposal_id, effective, user_id, iso(now), iso(closes_at)))
        if proposal_id is not None:
            self.db.execute("UPDATE proposals SET status='voting' WHERE id=?", (proposal_id,))
        self.db.commit()
        self.log(user_id, "vote_opened", {"id": cur.lastrowid, "kind": kind, "title": title}, now=now)
        return int(cur.lastrowid)

    def set_vote_message(self, vote_id: int, channel_id: int, message_id: int) -> None:
        self.db.execute("UPDATE votes SET channel_id=?, message_id=? WHERE id=?", (channel_id, message_id, vote_id))
        self.db.commit()

    def vote(self, vote_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM votes WHERE id=?", (vote_id,)).fetchone()

    def open_votes(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM votes WHERE status='open' ORDER BY id").fetchall()

    def due_to_close(self, now: datetime) -> list[sqlite3.Row]:
        return [v for v in self.open_votes() if parse(v["closes_at"]) <= now]

    def due_reminder(self, now: datetime, hours: float) -> list[sqlite3.Row]:
        out = []
        for v in self.open_votes():
            left = (parse(v["closes_at"]) - now).total_seconds() / 3600
            if not v["reminded"] and 0 < left <= hours:
                out.append(v)
        return out

    def mark_reminded(self, vote_id: int) -> None:
        self.db.execute("UPDATE votes SET reminded=1 WHERE id=?", (vote_id,))
        self.db.commit()

    def close_vote(self, vote_id: int, result: dict[str, Any], *, now: datetime, status: str = "closed") -> None:
        self.db.execute("UPDATE votes SET status=?, result=? WHERE id=?", (status, json.dumps(result), vote_id))
        row = self.vote(vote_id)
        if row and row["proposal_id"] is not None and status == "closed":
            self.db.execute("UPDATE proposals SET status=? WHERE id=?",
                            ("passed" if result.get("passed") else "failed", row["proposal_id"]))
        self.db.commit()
        self.log(None, f"vote_{status}", {"id": vote_id, **result}, now=now)

    # -- ballots -----------------------------------------------------------
    def cast(self, vote_id: int, franchise: str, choice: str, user_id: int, *, now: datetime) -> bool:
        """Record or replace a franchise's ballot. Returns True if it changed an earlier one."""
        before = self.db.execute("SELECT choice FROM ballots WHERE vote_id=? AND franchise=?",
                                 (vote_id, franchise)).fetchone()
        self.db.execute(
            "INSERT INTO ballots (vote_id, franchise, choice, user_id, cast_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(vote_id, franchise) DO UPDATE SET choice=excluded.choice, user_id=excluded.user_id, "
            "cast_at=excluded.cast_at",
            (vote_id, franchise, choice, user_id, iso(now)))
        self.db.commit()
        self.log(user_id, "ballot", {"vote": vote_id, "franchise": franchise}, now=now)
        return before is not None

    def ballots(self, vote_id: int) -> dict[str, str]:
        rows = self.db.execute("SELECT franchise, choice FROM ballots WHERE vote_id=?", (vote_id,)).fetchall()
        return {r["franchise"]: r["choice"] for r in rows}

    # -- orphans -----------------------------------------------------------
    def set_orphaned(self, franchise: str, orphaned: bool, user_id: int, *, now: datetime) -> None:
        if orphaned:
            self.db.execute("INSERT OR IGNORE INTO orphaned (franchise, since) VALUES (?, ?)", (franchise, iso(now)))
        else:
            self.db.execute("DELETE FROM orphaned WHERE franchise=?", (franchise,))
        self.db.commit()
        self.log(user_id, "orphaned" if orphaned else "unorphaned", {"franchise": franchise}, now=now)

    def orphaned(self) -> set[str]:
        return {r["franchise"] for r in self.db.execute("SELECT franchise FROM orphaned").fetchall()}

    # -- Pick'em -----------------------------------------------------------
    def add_pickem_week(self, season: str, period: int, matchups: list[dict[str, Any]], *,
                        locks_at: datetime, now: datetime) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO pickem_weeks (season, period, matchups, locks_at, posted_at) VALUES (?, ?, ?, ?, ?)",
            (season, period, json.dumps(matchups), iso(locks_at), iso(now)))
        self.db.commit()

    def set_pickem_message(self, season: str, period: int, channel_id: int, message_id: int) -> None:
        self.db.execute("UPDATE pickem_weeks SET channel_id=?, message_id=? WHERE season=? AND period=?",
                        (channel_id, message_id, season, period))
        self.db.commit()

    def pickem_week(self, season: str, period: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM pickem_weeks WHERE season=? AND period=?", (season, period)).fetchone()

    def pickem_week_by_message(self, message_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM pickem_weeks WHERE message_id=?", (message_id,)).fetchone()

    def pickem_statuses(self, season: str) -> dict[int, str]:
        rows = self.db.execute("SELECT period, status FROM pickem_weeks WHERE season=?", (season,)).fetchall()
        return {int(r["period"]): r["status"] for r in rows}

    def set_pickem_status(self, season: str, period: int, status: str, *, winners: dict[str, Any] | None = None,
                          now: datetime | None = None) -> None:
        if status == "scored":
            self.db.execute("UPDATE pickem_weeks SET status=?, winners=?, scored_at=? WHERE season=? AND period=?",
                            (status, json.dumps(winners or {}), iso(now) if now else None, season, period))
        else:
            self.db.execute("UPDATE pickem_weeks SET status=? WHERE season=? AND period=?", (status, season, period))
        self.db.commit()

    def pick(self, season: str, period: int, user_id: int, matchup: str, team_id: str, *, now: datetime) -> None:
        self.db.execute(
            "INSERT INTO pickem_picks (season, period, user_id, matchup, team_id, picked_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(season, period, user_id, matchup) DO UPDATE SET team_id=excluded.team_id, "
            "picked_at=excluded.picked_at",
            (season, period, user_id, matchup, team_id, iso(now)))
        self.db.commit()

    def user_picks(self, season: str, period: int, user_id: int) -> dict[str, str]:
        rows = self.db.execute("SELECT matchup, team_id FROM pickem_picks WHERE season=? AND period=? AND user_id=?",
                               (season, period, user_id)).fetchall()
        return {r["matchup"]: r["team_id"] for r in rows}

    def week_picks(self, season: str, period: int) -> list[tuple[int, str, str]]:
        rows = self.db.execute("SELECT user_id, matchup, team_id FROM pickem_picks WHERE season=? AND period=?",
                               (season, period)).fetchall()
        return [(int(r["user_id"]), r["matchup"], r["team_id"]) for r in rows]

    def scored_weeks(self, season: str) -> list[tuple[int, dict[str, Any]]]:
        rows = self.db.execute("SELECT period, winners FROM pickem_weeks WHERE season=? AND status='scored' "
                               "ORDER BY period", (season,)).fetchall()
        return [(int(r["period"]), json.loads(r["winners"] or "{}")) for r in rows]

    def latest_pickem_season(self) -> str | None:
        row = self.db.execute("SELECT season FROM pickem_weeks ORDER BY posted_at DESC LIMIT 1").fetchone()
        return row["season"] if row else None

    # -- Playoff Pool --------------------------------------------------------
    def pool_pick(self, year: int, franchise: str, box: int, player_id: int, user_id: int, *, now: datetime,
                  box_count: int) -> int:
        """Record or replace one box's pick. Returns how many boxes the entry has.

        The first time an entry has every box filled, that moment is its entry
        time (the pool's last tiebreak); later changes keep it.
        """
        self.db.execute(
            "INSERT INTO pool_picks (year, franchise, box, player_id, user_id, picked_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(year, franchise, box) DO UPDATE SET player_id=excluded.player_id, "
            "user_id=excluded.user_id, picked_at=excluded.picked_at",
            (year, franchise, box, player_id, user_id, iso(now)))
        count = int(self.db.execute("SELECT COUNT(*) FROM pool_picks WHERE year=? AND franchise=?",
                                    (year, franchise)).fetchone()[0])
        self.db.execute("INSERT OR IGNORE INTO pool_entries (year, franchise, completed_at) VALUES (?, ?, NULL)",
                        (year, franchise))
        if count >= box_count:
            self.db.execute("UPDATE pool_entries SET completed_at=? WHERE year=? AND franchise=? "
                            "AND completed_at IS NULL", (iso(now), year, franchise))
        self.db.commit()
        self.log(user_id, "pool_pick", {"year": year, "franchise": franchise, "box": box, "player": player_id},
                 now=now)
        return count

    def pool_picks(self, year: int, franchise: str) -> dict[int, int]:
        rows = self.db.execute("SELECT box, player_id FROM pool_picks WHERE year=? AND franchise=?",
                               (year, franchise)).fetchall()
        return {int(r["box"]): int(r["player_id"]) for r in rows}

    def pool_entries(self, year: int) -> list[tuple[str, dict[int, int], datetime | None]]:
        """[(franchise, box -> player id, entry time or None)], complete entries first, earliest first."""
        rows = self.db.execute("SELECT franchise, completed_at FROM pool_entries WHERE year=?", (year,)).fetchall()
        out = [(r["franchise"], self.pool_picks(year, r["franchise"]), parse(r["completed_at"])) for r in rows]
        out = [row for row in out if row[1]]
        return sorted(out, key=lambda r: (r[2] is None, r[2].isoformat() if r[2] else "", r[0]))
    # -- BLHA Bucks --------------------------------------------------------
    def add_book_week(self, season: str, period: int, lines: list[dict[str, Any]], *,
                      locks_at: datetime, now: datetime) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO book_weeks (season, period, lines, locks_at, posted_at) VALUES (?, ?, ?, ?, ?)",
            (season, period, json.dumps(lines), iso(locks_at), iso(now)))
        self.db.commit()

    def set_book_message(self, season: str, period: int, channel_id: int, message_id: int) -> None:
        self.db.execute("UPDATE book_weeks SET channel_id=?, message_id=? WHERE season=? AND period=?",
                        (channel_id, message_id, season, period))
        self.db.commit()

    def book_week(self, season: str, period: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM book_weeks WHERE season=? AND period=?", (season, period)).fetchone()

    def latest_book_week(self, status: str | None = None) -> sqlite3.Row | None:
        """The most recently posted Week (optionally only one with this status)."""
        if status:
            return self.db.execute("SELECT * FROM book_weeks WHERE status=? ORDER BY posted_at DESC, period DESC "
                                   "LIMIT 1", (status,)).fetchone()
        return self.db.execute("SELECT * FROM book_weeks ORDER BY posted_at DESC, period DESC LIMIT 1").fetchone()

    def book_statuses(self, season: str) -> dict[int, str]:
        rows = self.db.execute("SELECT period, status FROM book_weeks WHERE season=?", (season,)).fetchall()
        return {int(r["period"]): r["status"] for r in rows}

    def set_book_status(self, season: str, period: int, status: str, *, results: dict[str, Any] | None = None,
                        now: datetime | None = None) -> None:
        if status == "settled":
            self.db.execute("UPDATE book_weeks SET status=?, results=?, settled_at=? WHERE season=? AND period=?",
                            (status, json.dumps(results or {}), iso(now) if now else None, season, period))
        else:
            self.db.execute("UPDATE book_weeks SET status=? WHERE season=? AND period=?", (status, season, period))
        self.db.commit()

    def place_bet(self, season: str, period: int, user_id: int, matchup: str, side: str, amount: int,
                  franchise: str, *, now: datetime) -> None:
        """Record, replace or (amount 0) remove a member's bet on one matchup."""
        if amount <= 0:
            self.db.execute("DELETE FROM book_bets WHERE season=? AND period=? AND user_id=? AND matchup=?",
                            (season, period, user_id, matchup))
        else:
            self.db.execute(
                "INSERT INTO book_bets (season, period, user_id, matchup, side, amount, franchise, placed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(season, period, user_id, matchup) DO UPDATE SET "
                "side=excluded.side, amount=excluded.amount, franchise=excluded.franchise, placed_at=excluded.placed_at",
                (season, period, user_id, matchup, side, int(amount), franchise, iso(now)))
        self.db.commit()
        self.log(user_id, "book_bet", {"season": season, "week": period, "matchup": matchup, "side": side,
                                       "amount": int(amount)}, now=now)

    def user_bets(self, season: str, period: int, user_id: int) -> dict[str, tuple[str, int]]:
        rows = self.db.execute("SELECT matchup, side, amount FROM book_bets WHERE season=? AND period=? AND user_id=? "
                               "ORDER BY placed_at", (season, period, user_id)).fetchall()
        return {r["matchup"]: (r["side"], int(r["amount"])) for r in rows}

    def week_bets(self, season: str, period: int) -> list[tuple[int, str, str, int, str]]:
        """(user id, matchup, side, amount, franchise) for every bet in a Week."""
        rows = self.db.execute("SELECT user_id, matchup, side, amount, franchise FROM book_bets WHERE season=? AND "
                               "period=? ORDER BY user_id, matchup", (season, period)).fetchall()
        return [(int(r["user_id"]), r["matchup"], r["side"], int(r["amount"]), r["franchise"]) for r in rows]

    def settled_book_weeks(self, season: str) -> list[tuple[int, list[dict[str, Any]], dict[str, Any]]]:
        """(week, lines, results) for every settled Week of a season, in order."""
        rows = self.db.execute("SELECT period, lines, results FROM book_weeks WHERE season=? AND status='settled' "
                               "ORDER BY period", (season,)).fetchall()
        return [(int(r["period"]), json.loads(r["lines"]), json.loads(r["results"] or "{}")) for r in rows]

    def latest_book_season(self) -> str | None:
        row = self.latest_book_week()
        return row["season"] if row else None

    def book_champions(self, season: str) -> list[int] | None:
        row = self.db.execute("SELECT user_ids FROM book_champions WHERE season=?", (season,)).fetchone()
        return [int(u) for u in json.loads(row["user_ids"])] if row else None

    def set_book_champions(self, season: str, user_ids: list[int], *, now: datetime) -> None:
        self.db.execute("INSERT OR REPLACE INTO book_champions (season, user_ids, awarded_at) VALUES (?, ?, ?)",
                        (season, json.dumps(list(user_ids)), iso(now)))
        self.db.commit()
        self.log(None, "book_sharp_role", {"season": season, "users": list(user_ids)}, now=now)

    # -- Awards Ballot -------------------------------------------------------
    def open_awards(self, season: int, nominees_json: str, *, user_id: int, now: datetime,
                    closes_at: datetime) -> None:
        self.db.execute("INSERT INTO awards_seasons (season, nominees, opened_by, opened_at, closes_at) "
                        "VALUES (?, ?, ?, ?, ?)", (season, nominees_json, user_id, iso(now), iso(closes_at)))
        self.db.commit()
        self.log(user_id, "awards_opened", {"season": season}, now=now)

    def awards_season(self, season: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM awards_seasons WHERE season=?", (season,)).fetchone()

    def latest_awards(self) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM awards_seasons ORDER BY season DESC LIMIT 1").fetchone()

    def awards_by_message(self, message_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM awards_seasons WHERE message_id=?", (message_id,)).fetchone()

    def set_awards_message(self, season: int, channel_id: int, message_id: int) -> None:
        self.db.execute("UPDATE awards_seasons SET channel_id=?, message_id=? WHERE season=?",
                        (channel_id, message_id, season))
        self.db.commit()

    def set_awards_nominees(self, season: int, nominees_json: str, *, user_id: int, now: datetime,
                            detail: Any = None) -> None:
        self.db.execute("UPDATE awards_seasons SET nominees=? WHERE season=?", (nominees_json, season))
        self.db.commit()
        self.log(user_id, "awards_nominee_added", {"season": season, **(detail or {})}, now=now)

    def awards_due_to_close(self, now: datetime) -> list[sqlite3.Row]:
        rows = self.db.execute("SELECT * FROM awards_seasons WHERE status='open'").fetchall()
        return [r for r in rows if parse(r["closes_at"]) <= now]

    def close_awards(self, season: int, *, now: datetime, user_id: int | None = None) -> None:
        self.db.execute("UPDATE awards_seasons SET status='closed', closed_at=? WHERE season=? AND status='open'",
                        (iso(now), season))
        self.db.commit()
        self.log(user_id, "awards_closed", {"season": season}, now=now)

    def set_awards_results(self, season: int, results: dict[str, Any], *, now: datetime, user_id: int) -> None:
        self.db.execute("UPDATE awards_seasons SET status='posted', results=?, posted_at=? WHERE season=?",
                        (json.dumps(results), iso(now), season))
        self.db.commit()
        self.log(user_id, "awards_results", {"season": season}, now=now)

    def set_award_choices(self, season: int, franchise: str, award: str, places: dict[int, str], *,
                          user_id: int, now: datetime) -> None:
        """Replace a franchise's 1st/2nd/3rd choices for one award (empty clears them)."""
        self.db.execute("DELETE FROM awards_votes WHERE season=? AND franchise=? AND award=?", (season, franchise, award))
        self.db.executemany(
            "INSERT INTO awards_votes (season, franchise, award, place, nominee, user_id, cast_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(season, franchise, award, int(place), nominee, user_id, iso(now)) for place, nominee in places.items()])
        self.db.commit()
        self.log(user_id, "awards_ballot", {"season": season, "franchise": franchise, "award": award}, now=now)

    def awards_ballot(self, season: int, franchise: str) -> dict[str, dict[int, str]]:
        rows = self.db.execute("SELECT award, place, nominee FROM awards_votes WHERE season=? AND franchise=?",
                               (season, franchise)).fetchall()
        out: dict[str, dict[int, str]] = {}
        for r in rows:
            out.setdefault(r["award"], {})[int(r["place"])] = r["nominee"]
        return {k: dict(sorted(v.items())) for k, v in out.items()}

    def awards_ballots(self, season: int) -> dict[str, dict[str, dict[int, str]]]:
        """Every franchise's ballot: franchise -> award -> place -> nominee id."""
        rows = self.db.execute("SELECT franchise, award, place, nominee FROM awards_votes WHERE season=?",
                               (season,)).fetchall()
        out: dict[str, dict[str, dict[int, str]]] = {}
        for r in rows:
            out.setdefault(r["franchise"], {}).setdefault(r["award"], {})[int(r["place"])] = r["nominee"]
        return out

    def save_ranks(self, season: int, ranks: dict[str, int], *, now: datetime) -> None:
        """A Season's final regular-season rank per franchise name (Comeback and Bust use the year before)."""
        self.db.execute("INSERT OR REPLACE INTO season_ranks (season, ranks, saved_at) VALUES (?, ?, ?)",
                        (season, json.dumps(ranks), iso(now)))
        self.db.commit()

    def ranks(self, season: int) -> dict[str, int] | None:
        row = self.db.execute("SELECT ranks FROM season_ranks WHERE season=?", (season,)).fetchone()
        return {k: int(v) for k, v in json.loads(row["ranks"]).items()} if row else None
