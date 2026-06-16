"""
NFL schedule ingestion — the full slate, played and scheduled.

Drives the Film Room game picker: completed games get a *post-game* breakdown,
upcoming games get a *pre-game* matchup preview. Sourced from nflverse/nfldata
(refreshes as results come in and as future schedules are released).
"""

from __future__ import annotations

import logging
import time

import pandas as pd
import requests

from gridiron import config

log = logging.getLogger(__name__)

SCHEDULE_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
DEFAULT_TTL_HOURS = 12

_COLS = ["game_id", "season", "game_type", "week", "gameday",
         "away_team", "home_team", "away_score", "home_score", "result", "status"]


def load_schedules(*, force: bool = False, ttl_hours: float = DEFAULT_TTL_HOURS,
                   timeout: int = 60) -> pd.DataFrame:
    """Return every game (past + scheduled) with a ``status`` column (cached)."""
    dest = config.RAW_DIR / "games.csv"
    stale = not dest.exists() or (time.time() - dest.stat().st_mtime) / 3600 >= ttl_hours
    if stale or force:
        log.info("Downloading schedules: %s", SCHEDULE_URL)
        resp = requests.get(SCHEDULE_URL, timeout=timeout)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    df = pd.read_csv(dest, low_memory=False)
    df["status"] = df["result"].notna().map({True: "played", False: "scheduled"})
    return df


def list_games(season: int, week: int | None = None, *,
               force: bool = False) -> pd.DataFrame:
    """Games for a season (optionally one week), tidy and ordered."""
    df = load_schedules(force=force)
    sub = df[df["season"] == season]
    if week is not None:
        sub = sub[sub["week"] == week]
    cols = [c for c in _COLS if c in sub.columns]
    return sub[cols].sort_values(["week", "gameday"], ignore_index=True)


def get_game(game_id: str, *, force: bool = False) -> pd.Series:
    """Return one game's row by id."""
    df = load_schedules(force=force)
    row = df[df["game_id"] == game_id]
    if row.empty:
        raise KeyError(f"game_id {game_id!r} not found in schedule")
    return row.iloc[0]
