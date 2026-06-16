"""
Current-roster + talent-grade ingestion for the Super Bowl Maxer.

Freshness-first by design — the NFL churns daily, so:
  * the roster is the **live** nflverse feed (trades/cuts/signings show up),
  * talent grades are joined on nflverse player id (no fragile name matching),
  * every pull is cached with a TTL and re-fetchable on demand (`force=True`),
  * outputs carry a ``data_as_of`` timestamp so staleness is always visible.

Talent = **production** (PFR Approximate Value) blended with an **external grade**
(Madden overall) — both all-position signals, joined by ``gsis_id``.

Sources:
  * rosters  — nflverse-data release  ``rosters/roster_{season}.parquet``
  * grades   — theedgepredictor/nfl-madden-data ``data/madden/dataset/{season}.parquet``
               (Madden ``overallrating`` + PFR ``last_season_av``, keyed to gsis_id)
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from pathlib import Path

import pandas as pd
import requests

from gridiron import config
from gridiron.ingestion.reference import canonical_team, classify_position

log = logging.getLogger(__name__)

ROSTER_URL = config.NFLVERSE_RELEASE_BASE + "/rosters/roster_{season}.parquet"
MADDEN_URL = ("https://raw.githubusercontent.com/theedgepredictor/"
              "nfl-madden-data/main/data/madden/dataset/{season}.parquet")
DEFAULT_TTL_HOURS = 24


def current_league_year(today: dt.date | None = None) -> int:
    """NFL league year — rolls over in March when the new league year opens."""
    today = today or dt.date.today()
    return today.year if today.month >= 3 else today.year - 1


# --------------------------------------------------------------------------- #
# Cached downloads
# --------------------------------------------------------------------------- #
def _cached_download(url: str, dest: Path, ttl_hours: float, force: bool,
                     timeout: int = 90) -> Path:
    if dest.exists() and not force:
        age_h = (time.time() - dest.stat().st_mtime) / 3600
        if age_h < ttl_hours:
            log.info("Cache hit (%.1fh old): %s", age_h, dest.name)
            return dest
    log.info("Downloading %s", url)
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest


def _latest_available(url_tmpl: str, dest_tmpl: str, season: int, look_back: int,
                      ttl_hours: float, force: bool) -> tuple[int, Path]:
    """Download the newest available season at or before ``season``."""
    last_err: Exception | None = None
    for s in range(season, season - look_back - 1, -1):
        try:
            path = _cached_download(url_tmpl.format(season=s),
                                    config.RAW_DIR / dest_tmpl.format(season=s),
                                    ttl_hours, force)
            return s, path
        except requests.RequestException as exc:  # pragma: no cover - network
            last_err = exc
    raise RuntimeError(f"No data found near season {season}: {last_err}")


def load_current_roster(season: int | None = None, *, ttl_hours: float = DEFAULT_TTL_HOURS,
                        force: bool = False) -> tuple[int, pd.DataFrame]:
    """Return ``(season, roster)`` for the newest available roster feed."""
    season = season or current_league_year()
    yr, path = _latest_available(ROSTER_URL, "roster_{season}.parquet",
                                 season, look_back=1, ttl_hours=ttl_hours, force=force)
    return yr, pd.read_parquet(path)


def load_madden(season: int | None = None, *, ttl_hours: float = DEFAULT_TTL_HOURS,
                force: bool = False) -> tuple[int, pd.DataFrame]:
    """Return ``(season, grades)`` for the newest available Madden dataset."""
    season = season or current_league_year()
    yr, path = _latest_available(MADDEN_URL, "madden_{season}.parquet",
                                 season, look_back=2, ttl_hours=ttl_hours, force=force)
    return yr, pd.read_parquet(path)


def _best_pos_group(depth_pos, base_pos) -> str:
    """Prefer the granular depth-chart position; fall back to the coarse one."""
    grp = classify_position(depth_pos)
    return grp if grp != "UNK" else classify_position(base_pos)


def load_av_history(base_season: int, *, force: bool = False) -> pd.DataFrame:
    """Per-player Approximate Value for the last 3 seasons (trend signal).

    Each Madden file carries the *prior* season's AV, so loading three
    consecutive files yields three consecutive seasons of production keyed by
    ``gsis_id``: ``av0`` (most recent) → ``av2`` (oldest).
    """
    out: pd.DataFrame | None = None
    for i, yr in enumerate((base_season, base_season - 1, base_season - 2)):
        try:
            _, mad = load_madden(yr, force=force)
        except RuntimeError:  # pragma: no cover - older file missing
            continue
        col = f"av{i}"
        sub = (mad[["player_id", "last_season_av"]]
               .rename(columns={"player_id": "gsis_id", "last_season_av": col})
               .dropna(subset=["gsis_id"]).drop_duplicates("gsis_id"))
        out = sub if out is None else out.merge(sub, on="gsis_id", how="outer")
    if out is None:
        out = pd.DataFrame(columns=["gsis_id"])
    for col in ("av0", "av1", "av2"):
        if col not in out:
            out[col] = pd.NA
    return out


# --------------------------------------------------------------------------- #
# Join: who is on the roster now × how good they are
# --------------------------------------------------------------------------- #
def build_player_talent(season: int | None = None, *, force: bool = False
                        ) -> tuple[pd.DataFrame, dict]:
    """Join the live roster to talent grades; return ``(players, meta)``.

    ``players`` columns: gsis_id, player, team, pos_group, depth_chart_position,
    years_exp, madden_ovr, last_av. ``meta`` records the source seasons and the
    ``data_as_of`` timestamp.
    """
    roster_season, roster = load_current_roster(season, force=force)
    madden_season, madden = load_madden(season, force=force)

    active = roster[roster.get("status", "ACT").eq("ACT")] if "status" in roster else roster
    cols = ["gsis_id", "full_name", "team", "position",
            "depth_chart_position", "years_exp", "birth_date"]
    players = active[[c for c in cols if c in active.columns]].copy()
    players = players.rename(columns={"full_name": "player"})
    players["team"] = players["team"].map(canonical_team)
    # nflverse `position` is coarse (all DBs -> "DB", all D-line -> "DL"), which
    # erases the EDGE/IDL and CB/S splits the thesis hinges on. depth_chart_position
    # is granular (CB/FS/SS, DT/NT/DE/OLB) -> classify from it, fall back to coarse.
    players["pos_group"] = [
        _best_pos_group(d, p) for d, p in
        zip(players.get("depth_chart_position"), players["position"])
    ]
    # Age as of the season kickoff (Sept 1) — feeds the age-decline adjustment.
    birth = pd.to_datetime(players.get("birth_date"), errors="coerce")
    players["age"] = (
        (pd.Timestamp(year=roster_season, month=9, day=1) - birth).dt.days / 365.25
    ).round(1)

    grades = madden.rename(columns={"player_id": "gsis_id",
                                    "overallrating": "madden_ovr"})
    grades = grades[["gsis_id", "madden_ovr"]].dropna(subset=["gsis_id"]).drop_duplicates("gsis_id")
    players = players.merge(grades, on="gsis_id", how="left")

    # 3-season AV history (production trend); last_av = most recent season.
    players = players.merge(load_av_history(madden_season, force=force),
                            on="gsis_id", how="left")
    players["last_av"] = players["av0"]

    players = players[players["pos_group"].ne("UNK") & players["team"].notna()]

    meta = {
        "roster_season": roster_season,
        "madden_season": madden_season,
        "data_as_of": dt.datetime.now().isoformat(timespec="seconds"),
        "n_players": len(players),
        "n_graded": int(players["madden_ovr"].notna().sum()),
    }
    log.info("Player talent: %s", meta)
    return players.reset_index(drop=True), meta


def build_free_agent_pool(season: int | None = None, *, force: bool = False
                          ) -> tuple[pd.DataFrame, dict]:
    """Available free agents = last season's players not on any current roster.

    Re-derived from the live current roster (so it stays fresh as teams sign
    players), scored with the same talent inputs as rostered players. Columns:
    gsis_id, player, last_team, pos_group, age, madden_ovr, last_av, av0..2.
    """
    season = season or current_league_year()
    cur_season, current = load_current_roster(season, force=force)
    prev_season, previous = load_current_roster(season - 1, force=force)
    madden_season, madden = load_madden(season, force=force)

    signed = set(current.loc[current.get("status", "ACT").eq("ACT")
                 if "status" in current else slice(None), "gsis_id"]
                 .dropna().astype(str))
    prev_active = previous[previous.get("status", "ACT").eq("ACT")] \
        if "status" in previous else previous
    fa = prev_active[~prev_active["gsis_id"].astype(str).isin(signed)].copy()

    cols = ["gsis_id", "full_name", "team", "position",
            "depth_chart_position", "years_exp", "birth_date"]
    fa = fa[[c for c in cols if c in fa.columns]].rename(
        columns={"full_name": "player", "team": "last_team"})
    fa["last_team"] = fa["last_team"].map(canonical_team)
    fa["pos_group"] = [
        _best_pos_group(d, p) for d, p in
        zip(fa.get("depth_chart_position"), fa["position"])
    ]
    birth = pd.to_datetime(fa.get("birth_date"), errors="coerce")
    fa["age"] = (
        (pd.Timestamp(year=season, month=9, day=1) - birth).dt.days / 365.25
    ).round(1)

    grades = madden.rename(columns={"player_id": "gsis_id",
                                    "overallrating": "madden_ovr"})
    grades = grades[["gsis_id", "madden_ovr"]].dropna(subset=["gsis_id"]).drop_duplicates("gsis_id")
    fa = fa.merge(grades, on="gsis_id", how="left")
    fa = fa.merge(load_av_history(madden_season, force=force), on="gsis_id", how="left")
    fa["last_av"] = fa["av0"]

    # Keep only players with a real signal (a grade or recent production) — drops
    # the long tail of camp bodies / retirees with no data.
    fa = fa[fa["pos_group"].ne("UNK")]
    fa = fa[fa["madden_ovr"].notna() | fa["av0"].notna()]

    meta = {
        "roster_season": cur_season,
        "prev_season": prev_season,
        "madden_season": madden_season,
        "data_as_of": dt.datetime.now().isoformat(timespec="seconds"),
        "n_free_agents": len(fa),
    }
    log.info("Free-agent pool: %s", meta)
    return fa.reset_index(drop=True), meta
