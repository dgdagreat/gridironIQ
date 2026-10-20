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
SNAP_URL = config.NFLVERSE_RELEASE_BASE + "/snap_counts/snap_counts_{season}.parquet"
#: nflverse weekly player box score (gsis-keyed) — the in-season production feed.
WEEKLY_STATS_URL = (config.NFLVERSE_RELEASE_BASE
                    + "/stats_player/stats_player_week_{season}.parquet")
#: nflverse depth charts — timestamped snapshots; the latest defines who starts.
DEPTH_URL = config.NFLVERSE_RELEASE_BASE + "/depth_charts/depth_charts_{season}.parquet"
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
    config.atomic_write(dest, lambda p: p.write_bytes(resp.content))
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


def load_snap_counts(season: int, *, ttl_hours: float = DEFAULT_TTL_HOURS,
                     force: bool = False) -> pd.DataFrame:
    """nflverse per-game snap counts for ``season`` (all positions)."""
    path = _cached_download(SNAP_URL.format(season=season),
                            config.RAW_DIR / f"snap_counts_{season}.parquet",
                            ttl_hours, force)
    return pd.read_parquet(path)


def games_played(season: int, id_crosswalk: pd.DataFrame, *,
                 force: bool = False) -> pd.Series:
    """Regular-season games each player actually played in ``season`` (by gsis_id).

    A game with any snap (offense / defense / special teams) counts as played, so
    an injury-shortened year reads as a low total (a full season is 17). Snap
    counts are keyed by PFR id, so ``id_crosswalk`` (columns pfr_id, gsis_id) maps
    them to gsis_id. Returns an empty series if that season isn't posted yet.
    """
    try:
        snaps = load_snap_counts(season, force=force)
    except requests.RequestException:  # pragma: no cover - season not posted yet
        return pd.Series(dtype="float64", name="games_av0")
    reg = snaps[snaps.get("game_type", pd.Series("REG", index=snaps.index)).eq("REG")]
    played = reg[["offense_snaps", "defense_snaps", "st_snaps"]].fillna(0).sum(axis=1) > 0
    gp = (reg[played].groupby("pfr_player_id")["game_id"].nunique()
          .rename("games").reset_index())
    xwalk = id_crosswalk.dropna(subset=["pfr_id", "gsis_id"]).drop_duplicates("pfr_id")
    gp = gp.merge(xwalk, left_on="pfr_player_id", right_on="pfr_id", how="inner")
    return gp.set_index("gsis_id")["games"].rename("games_av0")


# --------------------------------------------------------------------------- #
# In-season (current-year) performance signal
# --------------------------------------------------------------------------- #
def load_weekly_stats(season: int, *, ttl_hours: float = DEFAULT_TTL_HOURS,
                      force: bool = False) -> pd.DataFrame:
    """nflverse weekly player box score for ``season`` (gsis-keyed, all positions)."""
    path = _cached_download(WEEKLY_STATS_URL.format(season=season),
                            config.RAW_DIR / f"stats_player_week_{season}.parquet",
                            ttl_hours, force)
    return pd.read_parquet(path)


def load_depth_charts(season: int, *, ttl_hours: float = DEFAULT_TTL_HOURS,
                      force: bool = False) -> pd.Series:
    """Current depth-chart rank per player (``gsis_id`` → best ``pos_rank``).

    nflverse publishes depth charts as timestamped snapshots; only the **latest**
    ``dt`` reflects today's lineup (trades/injuries resolved), so we keep that one.
    ``pos_rank`` is 1 for a starter at a slot, 2 for the backup, etc.; a player's
    *best* (minimum) rank across formations is his standing. Special-teams rows are
    dropped so a kick returner isn't mistaken for a starter at his base position.
    Returns an empty series if the season isn't posted yet.
    """
    try:
        path = _cached_download(DEPTH_URL.format(season=season),
                                config.RAW_DIR / f"depth_charts_{season}.parquet",
                                ttl_hours, force)
    except requests.RequestException:  # pragma: no cover - season not posted yet
        return pd.Series(dtype="float64", name="depth_rank")
    dc = pd.read_parquet(path)
    if "dt" not in dc.columns or dc.empty:
        return pd.Series(dtype="float64", name="depth_rank")
    latest = dc[dc["dt"] == dc["dt"].max()]
    if "pos_grp" in latest.columns:
        latest = latest[~latest["pos_grp"].eq("Special Teams")]
    latest = latest.dropna(subset=["gsis_id"])
    return latest.groupby("gsis_id")["pos_rank"].min().rename("depth_rank")


#: Position-appropriate per-game production. Each position is scored on the
#: box-score signals that actually capture its value, so the number is only
#: comparable *within* a position group (percentile-ranked downstream). OL and
#: specialists have no box-score production here and stay NaN (they fall back to
#: the static grade + depth-chart standing).
def _performance_composite(df: pd.DataFrame) -> pd.Series:
    """Per-game production score per player, position-appropriate (NaN if n/a)."""
    g = df["games_2026"].clip(lower=1)
    out = pd.Series(float("nan"), index=df.index, dtype="float64")
    p = df["pos_group"]
    f = lambda c: pd.to_numeric(df.get(c), errors="coerce").fillna(0.0)
    pass_epa, rush_epa, rec_epa = f("pass_epa"), f("rush_epa"), f("rec_epa")
    rec_yds, rush_yds = f("rec_yds"), f("rush_yds")
    tgt_share, cpoe = f("tgt_share"), f("cpoe")
    sacks, qbh, tfl = f("sacks"), f("qbh"), f("tfl")
    tkl, ast = f("tkl"), f("ast")
    ints, pdef = f("ints"), f("pdef")
    tackles = tkl + 0.5 * ast
    pass_rush = sacks + 0.4 * qbh + 0.4 * tfl

    out[p.eq("QB")] = ((pass_epa + 0.6 * rush_epa) / g + 2.0 * cpoe)[p.eq("QB")]
    out[p.eq("RB")] = ((rush_epa + rec_epa) / g
                       + 0.0015 * (rush_yds + rec_yds) / g)[p.eq("RB")]
    wrte = p.isin(["WR", "TE"])
    out[wrte] = (rec_epa / g + 0.012 * rec_yds / g + 8.0 * tgt_share)[wrte]
    dl = p.isin(["EDGE", "IDL"])
    out[dl] = ((pass_rush + 0.1 * tackles) / g)[dl]
    out[p.eq("LB")] = ((0.2 * tackles + 0.8 * sacks + 0.4 * tfl
                        + 0.5 * pdef + 1.0 * ints) / g)[p.eq("LB")]
    db = p.isin(["CB", "S"])
    out[db] = ((1.2 * ints + 0.6 * pdef + 0.08 * tackles) / g)[db]
    return out


#: Weekly columns we sum (or average) per player into a season-to-date line.
_WEEKLY_SUMS = {
    "passing_epa": "pass_epa", "rushing_epa": "rush_epa", "receiving_epa": "rec_epa",
    "receiving_yards": "rec_yds", "rushing_yards": "rush_yds",
    "def_sacks": "sacks", "def_qb_hits": "qbh", "def_tackles_for_loss": "tfl",
    "def_tackles_solo": "tkl", "def_tackle_assists": "ast",
    "def_interceptions": "ints", "def_pass_defended": "pdef",
}
_WEEKLY_MEANS = {"target_share": "tgt_share", "passing_cpoe": "cpoe"}


def player_performance(season: int, pos_by_gsis: pd.DataFrame,
                       id_crosswalk: pd.DataFrame, *, force: bool = False
                       ) -> pd.DataFrame:
    """Current-season production per player → ``gsis_id, perf_raw, games_2026, snaps_2026``.

    Aggregates the weekly box score into a season-to-date line, counts games and
    snaps actually played, and scores each player on a position-appropriate
    per-game composite (:func:`_performance_composite`). ``pos_by_gsis`` supplies
    the authoritative roster position group (the weekly feed's own position label
    is unreliable — e.g. an interior lineman tagged "DE"). Returns an empty frame
    if the season's weekly feed isn't posted yet, so the caller falls back to the
    static grades cleanly.
    """
    try:
        weekly = load_weekly_stats(season, force=force)
    except requests.RequestException:  # pragma: no cover - season not posted yet
        return pd.DataFrame(columns=["gsis_id", "perf_raw", "games_2026", "snaps_2026"])
    reg = weekly[weekly.get("season_type", pd.Series("REG", index=weekly.index)).eq("REG")]

    agg = {src: (src, "sum") for src in _WEEKLY_SUMS}
    agg.update({src: (src, "mean") for src in _WEEKLY_MEANS})
    stats = (reg.groupby("player_id").agg(games_wk=("week", "nunique"), **agg)
             .reset_index().rename(columns={"player_id": "gsis_id",
                                            **_WEEKLY_SUMS, **_WEEKLY_MEANS}))

    # Snaps + games actually played (any snap counts), keyed by gsis via crosswalk.
    try:
        snaps = load_snap_counts(season, force=force)
        reg_s = snaps[snaps.get("game_type", pd.Series("REG", index=snaps.index)).eq("REG")]
        xwalk = (id_crosswalk.dropna(subset=["pfr_id", "gsis_id"])
                 .drop_duplicates("pfr_id"))
        reg_s = reg_s.merge(xwalk, left_on="pfr_player_id", right_on="pfr_id", how="inner")
        reg_s["snaps"] = reg_s[["offense_snaps", "defense_snaps"]].fillna(0).sum(axis=1)
        snp = (reg_s.groupby("gsis_id")
               .agg(snaps_2026=("snaps", "sum"), games_snap=("game_id", "nunique"))
               .reset_index())
    except requests.RequestException:  # pragma: no cover - season not posted yet
        snp = pd.DataFrame(columns=["gsis_id", "snaps_2026", "games_snap"])

    out = stats.merge(snp, on="gsis_id", how="outer")
    out = out.merge(pos_by_gsis[["gsis_id", "pos_group"]].drop_duplicates("gsis_id"),
                    on="gsis_id", how="left")
    out["games_2026"] = out[["games_wk", "games_snap"]].max(axis=1).fillna(0)
    out["snaps_2026"] = pd.to_numeric(out["snaps_2026"], errors="coerce").fillna(0)
    out["perf_raw"] = _performance_composite(out)
    return out[["gsis_id", "perf_raw", "games_2026", "snaps_2026"]]


# --------------------------------------------------------------------------- #
# Join: who is on the roster now × how good they are
# --------------------------------------------------------------------------- #
def build_player_talent(season: int | None = None, *, force: bool = False,
                        augment_espn: bool = True) -> tuple[pd.DataFrame, dict]:
    """Join the live roster to talent grades; return ``(players, meta)``.

    ``players`` columns: gsis_id, player, team, pos_group, age, madden_ovr,
    last_av, source. With ``augment_espn`` (default), players ESPN lists that
    nflverse hasn't ingested yet (recent signings, rookies) are merged in so the
    roster is complete and current. ``meta`` records source seasons + timestamp.
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
    players["source"] = "nflverse"

    # Auto-fill ESPN-only players (recent signings / rookies nflverse hasn't picked
    # up) so the roster is complete and current; graded below by gsis_id if mapped.
    if augment_espn:
        try:
            from gridiron.ingestion import espn_roster
            extra = espn_roster.espn_only_players(force=force).assign(source="espn")
            players = pd.concat([players, extra], ignore_index=True)
        except Exception as exc:  # noqa: BLE001 - augmentation must not break the build
            log.warning("ESPN roster augmentation skipped: %s", exc)

    grades = madden.rename(columns={"player_id": "gsis_id",
                                    "overallrating": "madden_ovr"})
    grades = grades[["gsis_id", "madden_ovr"]].dropna(subset=["gsis_id"]).drop_duplicates("gsis_id")
    # Madden overall is an integer scale; the source ships averaged/interpolated
    # fractions for ~25% of players -- round back to a whole rating.
    grades["madden_ovr"] = grades["madden_ovr"].round()
    players = players.merge(grades, on="gsis_id", how="left")

    # 3-season AV history (production trend); last_av = most recent season.
    players = players.merge(load_av_history(madden_season, force=force),
                            on="gsis_id", how="left")
    players["last_av"] = players["av0"]

    # Availability: regular-season games played in the season av0 reflects. The
    # Madden file's AV lags one year (av0 ≈ madden_season - 1), so a low total
    # there means the player missed time that year — the talent model uses it to
    # avoid punishing a returning player for an injury-shortened season (see
    # roster_strength.player_talent_scores).
    av0_season = madden_season - 1
    xwalk = roster[[c for c in ("pfr_id", "gsis_id") if c in roster.columns]]
    if {"pfr_id", "gsis_id"}.issubset(xwalk.columns):
        players["games_av0"] = players["gsis_id"].map(
            games_played(av0_season, xwalk, force=force))
    else:
        players["games_av0"] = pd.NA

    # Current-season (in-season) production + who is actually starting right now.
    # These drive the live performance blend in roster_strength: a player
    # dominating this year climbs regardless of age/Madden, and the units are
    # built from the real depth-chart starters. Both degrade gracefully to empty
    # (→ static grades only) before a season is posted.
    perf = player_performance(roster_season, players[["gsis_id", "pos_group"]],
                              xwalk, force=force)
    players = players.merge(perf, on="gsis_id", how="left")
    for col in ("games_2026", "snaps_2026"):
        players[col] = pd.to_numeric(players[col], errors="coerce").fillna(0)
    players["depth_rank"] = players["gsis_id"].map(
        load_depth_charts(roster_season, force=force))

    players = players[players["pos_group"].ne("UNK") & players["team"].notna()]

    perf_qual = (players["games_2026"] >= 2) & players["perf_raw"].notna()
    meta = {
        "roster_season": roster_season,
        "madden_season": madden_season,
        "av0_season": av0_season,
        "perf_season": roster_season,
        "data_as_of": dt.datetime.now().isoformat(timespec="seconds"),
        "n_players": len(players),
        "n_graded": int(players["madden_ovr"].notna().sum()),
        "n_espn_added": int((players["source"] == "espn").sum()),
        "n_injury_flag": int(
            (pd.to_numeric(players["games_av0"], errors="coerce") < 8).sum()),
        "n_perf": int(perf_qual.sum()),
        "n_starters": int((players["depth_rank"] == 1).sum()),
    }
    log.info("Player talent: %s", meta)
    return players.reset_index(drop=True), meta


def build_free_agent_pool(season: int | None = None, *, force: bool = False,
                          augment_espn: bool = True) -> tuple[pd.DataFrame, dict]:
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
    # Players ESPN lists as rostered aren't free agents either (keeps the FA pool
    # consistent with the ESPN-augmented roster — e.g. don't offer Aiyuk to teams).
    if augment_espn:
        try:
            from gridiron.ingestion import espn_roster
            idmap = espn_roster.espn_to_gsis(force=force)
            signed |= set(espn_roster.load_espn_roster()["espn_id"].map(idmap).dropna().astype(str))
        except Exception as exc:  # noqa: BLE001
            log.warning("ESPN FA exclusion skipped: %s", exc)
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
    grades["madden_ovr"] = grades["madden_ovr"].round()  # integer Madden scale
    fa = fa.merge(grades, on="gsis_id", how="left")
    fa = fa.merge(load_av_history(madden_season, force=force), on="gsis_id", how="left")
    fa["last_av"] = fa["av0"]

    # Estimated market cost = the player's most recent contract APY ($M).
    from gridiron.ingestion import cap_data
    fa["est_apy"] = fa["gsis_id"].map(cap_data.latest_apy())

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
