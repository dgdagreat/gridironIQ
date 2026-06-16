"""
Film Room stage 1: extract per-game performance metrics from play-by-play.

Reads nflfastR play-by-play directly from the nflverse data releases (same
release-asset pattern as the cap layer) and distills one game into the tactical
metrics the Anthropic breakdown reasons over.

Coverage note: nflfastR play-by-play supports EPA/success, pressure (via
``qb_hit``/``sack``), turnovers, red-zone and down efficiency, and YAC directly.
A few requested metrics are *charting* data that live outside play-by-play and
are wired in a later pass from nflverse Next Gen Stats / PFR:
    * WR separation          -> NGS receiving (``ngs_receiving``)
    * true yards after contact-> PFR rushing (``yards_after_contact``)
These are surfaced as ``None`` with a clear flag rather than faked from YAC.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import requests

from gridiron import config

log = logging.getLogger(__name__)

PBP_URL = (
    f"{config.NFLVERSE_RELEASE_BASE}/pbp/play_by_play_{{season}}.parquet"
)

#: Metrics that require charting feeds not present in play-by-play (phase 2).
CHARTING_METRICS = ("wr_separation", "yards_after_contact")


def load_pbp(season: int, force: bool = False, timeout: int = 120) -> pd.DataFrame:
    """Download (cached) and return one season of nflfastR play-by-play."""
    dest = config.RAW_DIR / f"pbp_{season}.parquet"
    if not dest.exists() or force:
        url = PBP_URL.format(season=season)
        log.info("Downloading play-by-play: %s", url)
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        log.info("Saved %.1f MB -> %s", len(resp.content) / 1e6, dest)
    return pd.read_parquet(dest)


def list_games(pbp: pd.DataFrame) -> pd.DataFrame:
    """Return one row per game: game_id, week, home/away, final score."""
    cols = ["game_id", "week", "home_team", "away_team",
            "home_score", "away_score"]
    games = pbp[cols].drop_duplicates("game_id").reset_index(drop=True)
    games["winner"] = games.apply(
        lambda r: r.home_team if r.home_score > r.away_score else r.away_team, axis=1)
    games["loser"] = games.apply(
        lambda r: r.away_team if r.home_score > r.away_score else r.home_team, axis=1)
    return games


def team_offense_metrics(pbp: pd.DataFrame, game_id: str, team: str) -> dict:
    """Tactical offensive metrics for ``team`` in one game (posteam == team)."""
    g = pbp[(pbp["game_id"] == game_id) & (pbp["posteam"] == team)]
    plays = g[g["play_type"].isin(["pass", "run"])]
    dropbacks = g[g.get("qb_dropback", g["play_type"].eq("pass")) == 1] \
        if "qb_dropback" in g else g[g["play_type"].eq("pass")]

    def rate(numer, denom):
        return round(float(numer) / float(denom), 3) if denom else None

    rz = g[g["yardline_100"] <= 20]
    rz_td = rz["touchdown"].sum() if "touchdown" in rz else 0
    pass_plays = plays[plays["play_type"].eq("pass")]
    explosive = plays[((plays["play_type"].eq("pass")) & (plays["yards_gained"] >= 20)) |
                      ((plays["play_type"].eq("run")) & (plays["yards_gained"] >= 10))]

    return {
        "team": team,
        "plays": int(len(plays)),
        "epa_per_play": round(float(plays["epa"].mean()), 3) if len(plays) else None,
        "success_rate": round(float(plays["success"].mean()), 3) if "success" in plays and len(plays) else None,
        "pass_epa": round(float(pass_plays["epa"].mean()), 3) if len(pass_plays) else None,
        "rush_epa": round(float(plays[plays.play_type.eq("run")]["epa"].mean()), 3) if len(plays) else None,
        "explosive_play_rate": rate(len(explosive), len(plays)),
        "third_down_conv_rate": _third_down_rate(g),
        "red_zone_td_rate": rate(rz_td, max(g["drive"].nunique() and len(rz.drop_duplicates("drive")), 0)) if "drive" in g else None,
        "pressure_rate_allowed": rate(g["qb_hit"].sum() + g["sack"].sum(), len(dropbacks)) if {"qb_hit", "sack"} <= set(g.columns) else None,
        "sacks_allowed": int(g["sack"].sum()) if "sack" in g else None,
        "turnovers": int(g["interception"].sum() + g.get("fumble_lost", pd.Series(dtype=float)).sum()),
        "yac_per_completion": round(float(pass_plays.loc[pass_plays.complete_pass.eq(1), "yards_after_catch"].mean()), 2)
        if {"complete_pass", "yards_after_catch"} <= set(pass_plays.columns) and pass_plays.complete_pass.sum() else None,
        # charting-only metrics, filled by the NGS/PFR pass:
        "wr_separation": None,
        "yards_after_contact": None,
    }


def _third_down_rate(g: pd.DataFrame) -> float | None:
    if "down" not in g:
        return None
    third = g[g["down"] == 3]
    if not len(third) or "first_down" not in third:
        return None
    return round(float(third["first_down"].mean()), 3)


def build_breakdown_payload(pbp: pd.DataFrame, game_id: str) -> dict:
    """Assemble the full metrics payload for a single game (both teams).

    This dict is the input to :func:`gridiron.filmroom.breakdown.generate_breakdown`.
    """
    games = list_games(pbp).set_index("game_id")
    if game_id not in games.index:
        raise KeyError(f"game_id {game_id!r} not found in play-by-play")
    row = games.loc[game_id]

    return {
        "game_id": game_id,
        "week": int(row["week"]),
        "winner": row["winner"],
        "loser": row["loser"],
        "score": {row["home_team"]: int(row["home_score"]),
                  row["away_team"]: int(row["away_score"])},
        "losing_offense": team_offense_metrics(pbp, game_id, row["loser"]),
        "winning_offense": team_offense_metrics(pbp, game_id, row["winner"]),
        "charting_metrics_pending": list(CHARTING_METRICS),
    }
