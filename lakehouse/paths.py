"""Where the medallion reads raw PBP and writes its Delta layers.

Everything is path-based Delta so the identical code runs on a laptop or a
Databricks cluster — only the two environment variables change:

    GRIDIRON_RAW_PBP   dir of raw nflfastR ``pbp_{season}.parquet`` files
                       (default: the gridiron package's data/raw)
    GRIDIRON_LAKE      root of the Delta lakehouse (bronze/silver/gold live under it)
                       (default: <repo>/data/lakehouse ; on Databricks set a Volume,
                        e.g. /Volumes/gridiron/pbp/lakehouse)
"""

from __future__ import annotations

import os
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

RAW_PBP_DIR = os.environ.get("GRIDIRON_RAW_PBP", str(_REPO / "data" / "raw"))
LAKE_ROOT = os.environ.get("GRIDIRON_LAKE", str(_REPO / "data" / "lakehouse"))

#: Full season range nflfastR publishes play-by-play for.
SEASON_MIN, SEASON_MAX = 1999, 2025

# Delta table locations (bronze = raw landing, silver = clean plays, gold = features).
BRONZE_PBP = f"{LAKE_ROOT}/bronze/pbp"
SILVER_PLAYS = f"{LAKE_ROOT}/silver/plays"
GOLD_TEAM_GAME = f"{LAKE_ROOT}/gold/team_game_epa"
GOLD_TEAM_SEASON = f"{LAKE_ROOT}/gold/team_season_epa"


def raw_pbp_path(season: int) -> str:
    """Path to one season's raw nflfastR parquet."""
    return f"{RAW_PBP_DIR}/pbp_{season}.parquet"
