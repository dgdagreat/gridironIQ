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


def team_form(pbp: pd.DataFrame, team: str, through_week: int | None = None) -> dict:
    """Season (or season-to-date) offense + defense identity for one team.

    The pre-game preview compares two of these. Covers EPA/efficiency on both
    sides of the ball plus pressure, explosives, and turnover margin.
    """
    df = pbp
    if through_week is not None and "week" in df.columns:
        df = df[df["week"] <= through_week]
    plays = ["pass", "run"]
    off = df[(df["posteam"] == team) & df["play_type"].isin(plays)]
    deff = df[(df["defteam"] == team) & df["play_type"].isin(plays)]
    games = df[(df["posteam"] == team) | (df["defteam"] == team)]["game_id"].nunique()
    g = max(games, 1)

    def mean(frame, col):
        return round(float(frame[col].mean()), 3) if len(frame) and col in frame else None

    def explosive(frame):
        if not len(frame):
            return None
        ex = frame[((frame["play_type"] == "pass") & (frame["yards_gained"] >= 20)) |
                   ((frame["play_type"] == "run") & (frame["yards_gained"] >= 10))]
        return round(len(ex) / len(frame), 3)

    def pressure(frame):
        db = frame[frame["play_type"] == "pass"]
        if not len(db) or not {"qb_hit", "sack"} <= set(frame.columns):
            return None
        return round(float((db["qb_hit"].sum() + db["sack"].sum()) / len(db)), 3)

    giveaways = float(off["interception"].sum()) + (
        float(off["fumble_lost"].sum()) if "fumble_lost" in off else 0.0)
    takeaways = float(deff["interception"].sum()) + (
        float(deff["fumble_lost"].sum()) if "fumble_lost" in deff else 0.0)

    return {
        "team": team, "games": int(games),
        "off_epa_per_play": mean(off, "epa"),
        "off_pass_epa": mean(off[off["play_type"] == "pass"], "epa"),
        "off_rush_epa": mean(off[off["play_type"] == "run"], "epa"),
        "off_success_rate": mean(off, "success"),
        "off_explosive_rate": explosive(off),
        "off_pressure_allowed": pressure(off),
        "def_epa_allowed": mean(deff, "epa"),
        "def_explosive_allowed": explosive(deff),
        "def_pressure_rate": pressure(deff),
        "giveaways_per_game": round(giveaways / g, 2),
        "takeaways_per_game": round(takeaways / g, 2),
    }


def key_players(pbp: pd.DataFrame, game_id: str, team: str) -> dict:
    """Name the players who drove (or sank) a team's game — attribution."""
    g = pbp[(pbp["game_id"] == game_id) & (pbp["posteam"] == team)]
    out: dict = {}
    if "passer_player_name" in g and g["passer_player_name"].notna().any():
        qb = g["passer_player_name"].value_counts().idxmax()
        qbp = g[g["passer_player_name"] == qb]
        out["qb"] = {
            "player": qb,
            "pass_epa": round(float(qbp["epa"].mean()), 3) if len(qbp) else None,
            "sacks_taken": int(g["sack"].sum()) if "sack" in g else None,
            "interceptions": int(qbp["interception"].sum()) if "interception" in qbp else None,
        }
    runs = g[g["play_type"] == "run"]
    if "rusher_player_name" in runs and runs["rusher_player_name"].notna().any():
        rb = runs["rusher_player_name"].value_counts().idxmax()
        rbp = runs[runs["rusher_player_name"] == rb]
        out["lead_rusher"] = {"player": rb, "carries": int(len(rbp)),
                              "rush_epa": round(float(rbp["epa"].mean()), 3)}
    if "receiver_player_name" in g and g["receiver_player_name"].notna().any():
        tgt = g["receiver_player_name"].value_counts().idxmax()
        tp = g[g["receiver_player_name"] == tgt]
        out["top_target"] = {"player": tgt, "targets": int(len(tp)),
                             "rec_epa": round(float(tp["epa"].mean()), 3)}
    givers: list[str] = []
    if "interception" in g:
        givers += g.loc[g["interception"] == 1, "passer_player_name"].dropna().tolist()
    if "fumble_lost" in g and "fumbled_1_player_name" in g:
        givers += g.loc[g["fumble_lost"] == 1, "fumbled_1_player_name"].dropna().tolist()
    if givers:
        out["gave_it_away"] = givers
    return out


def _situational(pbp: pd.DataFrame, game_id: str, team: str) -> dict:
    """By-down and by-half offensive EPA — was it script or scramble?"""
    g = pbp[(pbp["game_id"] == game_id) & (pbp["posteam"] == team)
            & pbp["play_type"].isin(["pass", "run"])]
    out: dict = {}
    if "down" in g:
        for d in (1, 2, 3):
            dd = g[g["down"] == d]
            out[f"down{d}_epa"] = round(float(dd["epa"].mean()), 3) if len(dd) else None
    if "qtr" in g:
        fh, sh = g[g["qtr"] <= 2], g[g["qtr"] >= 3]
        out["first_half_epa"] = round(float(fh["epa"].mean()), 3) if len(fh) else None
        out["second_half_epa"] = round(float(sh["epa"].mean()), 3) if len(sh) else None
    return out


def build_breakdown_payload(pbp: pd.DataFrame, game_id: str) -> dict:
    """Assemble the full post-game metrics payload for a single game (both teams).

    This dict is the input to :func:`gridiron.filmroom.breakdown.generate_breakdown`.
    """
    games = list_games(pbp).set_index("game_id")
    if game_id not in games.index:
        raise KeyError(f"game_id {game_id!r} not found in play-by-play")
    row = games.loc[game_id]

    return {
        "mode": "post",
        "game_id": game_id,
        "week": int(row["week"]),
        "winner": row["winner"],
        "loser": row["loser"],
        "score": {row["home_team"]: int(row["home_score"]),
                  row["away_team"]: int(row["away_score"])},
        "losing_offense": team_offense_metrics(pbp, game_id, row["loser"]),
        "winning_offense": team_offense_metrics(pbp, game_id, row["winner"]),
        "losing_key_players": key_players(pbp, game_id, row["loser"]),
        "winning_key_players": key_players(pbp, game_id, row["winner"]),
        "losing_situational": _situational(pbp, game_id, row["loser"]),
        "charting_metrics_pending": list(CHARTING_METRICS),
    }
