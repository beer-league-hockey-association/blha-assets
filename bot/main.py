#!/usr/bin/env python3
"""Start the BLHA League Bot.

Environment:
  DISCORD_TOKEN              bot token from the Discord Developer Portal (required)
  BLHA_DB_PATH               SQLite file, on a Railway volume (default /data/blha_votes.db)
  BLHA_BOT_CONFIG            settings file (default bot/config.yaml)
  BLHA_LEDGER_CLEARANCE_CSV  published-CSV link of the League Ledger's Pick Clearance tab
                             (/myteam "Paid through" and /tradecheck prepayment); optional
  BLHA_CHECK=1               validate the config and exit without connecting
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from blha_vote.config import load  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load(os.environ.get("BLHA_BOT_CONFIG") or HERE / "config.yaml")
    for problem in cfg.problems:
        logging.warning("Config: %s", problem)
    if os.environ.get("BLHA_CHECK"):
        print(f"BLHA League Bot config OK with {len(cfg.problems)} warning(s); {len(cfg.franchises)} franchises.")
        return 0
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token:
        logging.error("BLHA League Bot: DISCORD_TOKEN is not set.")
        return 1

    from blha_vote.app import VoteBot  # needs discord.py
    from blha_vote.store import Store

    if not os.environ.get("BLHA_LEDGER_CLEARANCE_CSV", "").strip():
        logging.warning("BLHA League Bot: BLHA_LEDGER_CLEARANCE_CSV is not set; /myteam and /tradecheck "
                        "can't read the League Ledger's paid-through Seasons.")
    store = Store(os.environ.get("BLHA_DB_PATH") or "/data/blha_votes.db")
    logging.info("Starting the BLHA League Bot")
    VoteBot(cfg, store).run(token, log_handler=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
