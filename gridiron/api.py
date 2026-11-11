"""FastAPI layer over the ``gridiron`` analytics — the JSON contract the React
frontend (``frontend/``) is built against.

The analytics functions already return tidy DataFrames, so every route is a
``_records(df)`` away. Run it with::

    PYTHONPATH=. .venv/bin/python -m uvicorn gridiron.api:app --reload --port 8000

The Streamlit app (``app/streamlit_app.py``) stays the canonical, feature-complete
frontend; this layer exposes the same analytics so the React build can port each
panel one at a time. Parity today: the full Boardroom (champion premium, the
efficiency verdict, team spending, archetypes) and the Film Room (schedule, a
no-LLM game summary, and the Anthropic-written breakdown).

Performance: the analytics tables only change when the refresh scripts rewrite
the DB, so everything derived from them is memoized per DB snapshot
(``_snapshot_cache``). Responses are gzipped and successful GETs are
browser-cacheable for a few minutes (``API_MAX_AGE_SECONDS``).
"""
from __future__ import annotations

import functools
import json
import threading
import time
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field

from gridiron import config, db
from gridiron.ingestion.reference import DIVISIONS, canonical_team
# ``clustering`` is imported inside its route: it pulls in scikit-learn, which is
# about 70% of this module's import time and only the archetypes panel needs it.
from gridiron.modeling import (cap_efficiency, roster_strength, sb_maxer,
                               trade_market, value_board)

app = FastAPI(title="GridironIQ API", version="0.1.0")

# The Vite dev server (and a built preview) call the API from a different origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",  # vite dev
        "http://localhost:4173", "http://127.0.0.1:4173",  # vite preview
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)
# JSON and the SPA bundle compress 4-5x; bodies under 1 KB are not worth the CPU.
app.add_middleware(GZipMiddleware, minimum_size=1024)

#: How long a browser may reuse a successful ``GET /api/...`` response. The data
#: behind them changes at most daily (the DB refresh) or hourly (live
#: play-by-play), so five minutes is invisible staleness and makes moving between
#: sections instant. The Vite dev proxy strips the header (``vite.config.js``).
API_MAX_AGE_SECONDS = 300


@app.middleware("http")
async def _cache_headers(request: Request, call_next):
    """Set ``Cache-Control`` on successful GETs that do not set their own."""
    response = await call_next(request)
    if (request.method == "GET" and response.status_code == 200
            and "cache-control" not in response.headers):
        path = request.url.path
        if path.startswith("/assets/"):
            # Vite fingerprints these filenames, so a given URL never changes.
            policy = "public, max-age=31536000, immutable"
        elif path == "/api/health":
            policy = "no-store"
        elif path.startswith("/api/"):
            policy = f"public, max-age={API_MAX_AGE_SECONDS}"
        else:
            # index.html (and SPA deep links): revalidate, so a deploy's new
            # asset URLs are picked up on the next load.
            policy = "no-cache"
        response.headers["Cache-Control"] = policy
    return response


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """DataFrame -> JSON-safe records.

    Round-tripping through ``df.to_json`` is the cheap way to get NaN -> null and
    numpy scalars (int64/float64) -> native JSON numbers, which plain
    ``to_dict(orient="records")`` leaves as un-serializable numpy types.
    """
    return json.loads(df.to_json(orient="records"))


def _db_stamp() -> float:
    """Identity of the DB snapshot being served: the SQLite file's mtime."""
    try:
        return config.DB_PATH.stat().st_mtime
    except OSError:
        return 0.0


def _snapshot_cache(*, ttl: float | None = None, maxsize: int = 32) -> Callable:
    """Memoize a function of the DB's contents until the DB file changes.

    The analytics tables are rewritten only by the refresh scripts, so anything
    derived purely from them is constant for a given DB file and is computed once
    per snapshot (per distinct positional arguments, up to ``maxsize``). ``ttl``
    additionally expires entries by age, for results that also depend on the
    schedule feed. One lock per function means concurrent first requests wait for
    a single computation instead of each repeating it.

    Cached values are shared between requests: treat them as read-only.
    """
    def decorate(fn: Callable) -> Callable:
        lock = threading.Lock()
        entries: dict[tuple, tuple[float, Any]] = {}
        seen_stamp: list[float | None] = [None]

        @functools.wraps(fn)
        def wrapper(*args):
            stamp, now = _db_stamp(), time.monotonic()
            with lock:
                if seen_stamp[0] != stamp:
                    entries.clear()
                    seen_stamp[0] = stamp
                hit = entries.get(args)
                if hit is not None and (ttl is None or now - hit[0] < ttl):
                    return hit[1]
                value = fn(*args)
                entries.pop(args, None)
                while len(entries) >= maxsize:
                    del entries[next(iter(entries))]
                entries[args] = (now, value)
                return value

        wrapper.cache_clear = entries.clear
        return wrapper
    return decorate


# --------------------------------------------------------------------------- #
# Meta — powers the UI's season/team dropdowns
# --------------------------------------------------------------------------- #
@_snapshot_cache()
def _seasons_teams() -> tuple[list[int], list[str]]:
    df = db.query("SELECT DISTINCT season, team FROM positional_spending")
    return (sorted((int(s) for s in df["season"].unique()), reverse=True),
            sorted(str(t) for t in df["team"].unique()))


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "gridiron-api"}


@app.get("/api/meta")
def meta() -> dict:
    seasons, teams = _seasons_teams()
    return {
        "seasons": seasons,
        "teams": teams,
        "current_season": config.CURRENT_SEASON,
        "projection_season": config.PROJECTION_SEASON,
        "divisions": {k: list(v) for k, v in DIVISIONS.items()},
    }


# --------------------------------------------------------------------------- #
# Boardroom
# --------------------------------------------------------------------------- #
@_snapshot_cache()
def _champion_premium() -> list[dict]:
    return _records(cap_efficiency.champion_premium().reset_index())


@_snapshot_cache()
def _efficiency_verdict() -> list[dict]:
    return _records(cap_efficiency.efficiency_verdict().reset_index())


@app.get("/api/champion-premium")
def champion_premium() -> list[dict]:
    """Per-position: champion cap share vs. the league, and the gap."""
    return _champion_premium()


@app.get("/api/efficiency-verdict")
def efficiency_verdict() -> list[dict]:
    """Premium + spend/win correlation rolled into a per-position verdict."""
    return _efficiency_verdict()


@app.get("/api/team-season/{team}/{season}")
def team_season(team: str, season: int) -> dict:
    """A team-season's positional cap roll-up plus the per-player atoms."""
    positions = db.query(
        "SELECT pos_group, cap_pct, cap_pct_norm, cap_dollars, n_players "
        "FROM positional_spending "
        "WHERE team = :t AND season = :s ORDER BY cap_pct_norm DESC",
        t=team, s=season,
    )
    if positions.empty:
        raise HTTPException(404, f"No spending data for {team} {season}")
    players = db.query(
        "SELECT player, position, cap_number, cap_percent "
        "FROM player_year_caps WHERE team = :t AND season = :s "
        "AND cap_number IS NOT NULL ORDER BY cap_number DESC",
        t=team, s=season,
    )
    # On-field efficiency (nflfastR EPA from the PBP lakehouse), with the team's
    # net-EPA/play rank for the season — powers the Boardroom "did the cap
    # allocation translate?" panel. Absent for projected/future seasons.
    epa: dict[str, Any] | None = None
    if db.table_exists("pbp_team_season_epa"):
        season_epa = db.query(
            "SELECT * FROM pbp_team_season_epa WHERE season = :s", s=season)
        if not season_epa.empty and (season_epa["team"] == team).any():
            row = season_epa.set_index("team").loc[team]
            epa = _records(season_epa[season_epa["team"] == team])[0]
            epa["net_epa_rank"] = int((season_epa["net_epa_play"] > row["net_epa_play"]).sum()) + 1
            epa["n_teams"] = int(len(season_epa))
    return {
        "team": team,
        "season": season,
        "league_cap": config.LEAGUE_SALARY_CAP.get(season),
        "positions": _records(positions),
        "players": _records(players),
        "epa": epa,
    }


@app.get("/api/compare")
def compare(season: int, teams: str) -> list[dict]:
    """Normalized positional cap share for up to six teams in a season — powers
    the Boardroom head-to-head / division comparison. ``teams`` is comma-separated
    (e.g. ``?season=2026&teams=KC,BUF,PHI``)."""
    wanted = [canonical_team(t.strip()) for t in teams.split(",") if t.strip()][:6]
    out: list[dict[str, Any]] = []
    for t in wanted:
        df = db.query(
            "SELECT pos_group, cap_pct_norm FROM positional_spending "
            "WHERE team = :t AND season = :s ORDER BY cap_pct_norm DESC",
            t=t, s=season,
        )
        if not df.empty:
            out.append({"team": t, "positions": _records(df)})
    return out


@_snapshot_cache()
def _archetypes(k: int) -> dict:
    from gridiron.modeling import clustering

    res = clustering.cluster_archetypes(k=k)
    success = res.success.join(res.profiles["label"]).reset_index()
    return {
        "k": k,
        "success": _records(success),
        "profiles": _records(res.profiles.reset_index()),
    }


@app.get("/api/archetypes")
def archetypes(k: int = 5) -> dict:
    """K-means spending archetypes with each cluster's SB success rate."""
    if not 2 <= k <= 10:
        raise HTTPException(400, "k must be between 2 and 10")
    return _archetypes(k)


# --------------------------------------------------------------------------- #
# Super Bowl Maxer + Value Board
# --------------------------------------------------------------------------- #
@_snapshot_cache()
def _player_talent() -> pd.DataFrame:
    return db.read_table("player_talent")


@_snapshot_cache()
def _roster_strength() -> pd.DataFrame:
    return db.read_table("roster_strength")


@_snapshot_cache()
def _free_agents() -> pd.DataFrame | None:
    """The free-agent pool, or ``None`` when the refresh has not produced one."""
    return db.read_table("free_agents") if db.table_exists("free_agents") else None


#: The league baseline also depends on the schedule feed (this season's results
#: move the outlook), which ``schedules`` refreshes every 12 hours.
_LEAGUE_BASELINE_TTL_SECONDS = 600


@_snapshot_cache(ttl=_LEAGUE_BASELINE_TTL_SECONDS)
def _league_baseline() -> tuple[sb_maxer.LeagueInputs, pd.DataFrame]:
    """The roster-independent outlook inputs and the stored rosters' league table.

    Both are the same for every team, so a Maxer request reuses them; a
    simulation reuses the inputs to rescore the roster it changed.
    """
    inputs = sb_maxer.league_inputs()
    return inputs, sb_maxer.league_table(_roster_strength(), inputs=inputs)


@app.get("/api/maxer/{team}")
def maxer(team: str) -> dict:
    """Team outlook, needs, available free agents and trade targets."""
    try:
        strength = _roster_strength()
        inputs, league = _league_baseline()
        report = sb_maxer.team_report(team, strength, inputs=inputs, table=league)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(404, f"No roster data for {team}") from exc
    players = _player_talent()
    needs = report["top_needs"]
    fa = _free_agents()
    if fa is not None:
        need_order = {pos: idx for idx, pos in enumerate(needs)}
        fa = fa.assign(_need=fa["pos_group"].map(need_order).fillna(99))
        fa = fa.sort_values(["_need", "talent"], ascending=[True, False]).head(30)
        fa = fa[[c for c in ("player", "pos_group", "age", "madden_ovr", "talent", "est_apy")
                 if c in fa.columns]]
    else:
        fa = pd.DataFrame()
    targets = trade_market.trade_board(players, team, needs, per_need=6)
    starters = _starter_board(team, players, strength, report["needs"])
    report["needs"] = _records(report["needs"])
    return {
        "team": team,
        "report": report,
        "free_agents": _records(fa),
        "trade_targets": _records(targets),
        "league": _records(league),
        "starters": starters,
    }


_FORMATION = [
    ("X", "WR", 3, 42.5, None), ("Z", "WR", 50, 42.5, None), ("SLOT", "WR", 10, 41, None),
    ("LT", "T", 16, 44, "T"), ("LG", "G", 21, 44, "G"), ("C", "C", 26.5, 44, "C"),
    ("RG", "G", 32, 44, "G"), ("RT", "T", 37, 44, "T"), ("TE", "TE", 42, 44, None),
    ("QB", "QB", 25, 38, None), ("RB", "RB", 31, 38, None),
    ("DE", "EDGE", 15, 47, None), ("DT", "IDL", 22, 47, None), ("DT", "IDL", 31, 47, None),
    ("DE", "EDGE", 38, 47, None), ("LB", "LB", 21, 51, None), ("LB", "LB", 32, 51, None),
    ("CB", "CB", 3, 47, None), ("CB", "CB", 50, 47, None), ("NB", "CB", 11, 50, None),
    ("FS", "S", 18, 58, "FS"), ("SS", "S", 35, 58, "SS"),
]


def _talent_percentiles(players: pd.DataFrame) -> pd.Series | None:
    """Each player's talent as a percentile (0-100) of the starters at his position.

    The comparison population is the position's depth-chart starters, as in
    Streamlit (everyone graded at the position when it has no starters). A sorted
    reference plus a binary search does this in one pass per position instead of
    one scan of the starters per player. ``None`` when there are no talent scores.
    """
    if "talent" not in players:
        return None
    starter = (players["depth_rank"].eq(1) if "depth_rank" in players
               else pd.Series(True, index=players.index))
    pct = pd.Series(np.nan, index=players.index, dtype=float)
    for _, group in players.groupby("pos_group"):
        talent = group["talent"]
        ref = talent[starter.loc[group.index]].dropna()
        if ref.empty:
            ref = talent.dropna()
        if ref.empty:
            continue
        values = talent.to_numpy(dtype=float)
        at_or_below = np.searchsorted(np.sort(ref.to_numpy(dtype=float)), values,
                                      side="right")
        pct.loc[group.index] = np.where(np.isnan(values), np.nan,
                                        at_or_below / len(ref) * 100)
    return pct


def _starter_board(team: str, players: pd.DataFrame, strength: pd.DataFrame,
                   needs: pd.DataFrame) -> list[dict[str, Any]]:
    """Assign likely starters to the same 11-personnel vs nickel field as Streamlit.

    ``needs`` is the team report's needs frame for this same ``strength``.
    """
    pool = players[players["team"] == team].copy()
    talent_pct = _talent_percentiles(players)
    if talent_pct is not None:
        pool["talent_pct"] = talent_pct.loc[pool.index]
    pool["_out"] = (pool["currently_out"].fillna(False).astype(bool)
                    if "currently_out" in pool else False)
    sort_cols, ascending = ["_out"], [True]
    if "depth_rank" in pool:
        sort_cols.append("depth_rank"); ascending.append(True)
    for col, direction in (("madden_ovr", False), ("talent", False)):
        if col in pool:
            sort_cols.append(col); ascending.append(direction)
    needs = needs.set_index("pos_group")
    # One stable sort up front; filtering it per slot keeps each position's order.
    pool = pool.sort_values(sort_cols, ascending=ascending, na_position="last")
    ranked = strength.assign(
        rank=strength.groupby("pos_group")["strength"].rank(ascending=False, method="min"))
    team_rank = ranked[ranked["team"] == team].set_index("pos_group")["rank"]
    n_teams = int(strength["team"].nunique())
    used: set[Any] = set()
    out: list[dict[str, Any]] = []
    for label, pos, x, y, bucket in _FORMATION:
        group = pool[pool["pos_group"] == pos]
        candidates = ([group[group["depth_chart_position"] == bucket]] if bucket and
                      "depth_chart_position" in group else []) + [group]
        selected = None
        for candidate in candidates:
            for _, row in candidate.iterrows():
                player_id = row.get("gsis_id", row.get("player"))
                if player_id not in used:
                    selected = row
                    used.add(player_id)
                    break
            if selected is not None:
                break
        unit = needs.loc[pos] if pos in needs.index else {}
        out.append({
            "label": label, "pos_group": pos, "x": x, "y": y,
            "player": selected.get("player") if selected is not None else None,
            "madden_ovr": selected.get("madden_ovr") if selected is not None else None,
            "talent": selected.get("talent") if selected is not None else None,
            "grade_pct": selected.get("talent_pct") if selected is not None else None,
            "out": bool(selected.get("_out")) if selected is not None else False,
            "strength": float(unit.get("strength", 0)) if hasattr(unit, "get") else 0,
            "rank": int(team_rank.get(pos, n_teams)), "n_teams": n_teams,
        })
    return out


class MaxerSimulationRequest(BaseModel):
    signed: list[str] = Field(default_factory=list)
    traded: list[str] = Field(default_factory=list)

    class Config:
        extra = "forbid"


@app.post("/api/maxer/{team}/simulate")
def maxer_simulate(team: str, body: MaxerSimulationRequest) -> dict:
    """Recompute team outlook after the selected free-agent signings/trades."""
    team = canonical_team(team)
    if team is None:
        raise HTTPException(400, "Unknown team")
    signed = list(dict.fromkeys(body.signed))
    traded = list(dict.fromkeys(body.traded))
    if len(signed) + len(traded) > 12:
        raise HTTPException(400, "Select no more than 12 total moves")
    try:
        strength = _roster_strength()
        inputs, league = _league_baseline()
        baseline = sb_maxer.team_report(team, strength, inputs=inputs, table=league)
        players = _player_talent().copy()
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(404, f"No roster data for {team}") from exc
    if traded:
        eligible = trade_market.trade_board(
            players, team, baseline["top_needs"], per_need=6)
        available_ids = (set(eligible["gsis_id"].dropna().astype(str))
                         if "gsis_id" in eligible else set())
        if set(traded) - available_ids:
            raise HTTPException(
                400, "One or more trade targets are unavailable or not on the trade board")
        moved = players["gsis_id"].astype(str).isin(set(map(str, traded)))
        players.loc[moved, "team"] = team
        players.loc[moved, "depth_rank"] = 0
        players.loc[moved, "currently_out"] = False
    if signed:
        fa = _free_agents()
        if fa is None:
            raise HTTPException(404, "Free-agent data is unavailable")
        adds = fa[fa["player"].isin(signed)].copy()
        if len(adds) != len(signed):
            raise HTTPException(400, "One or more selected free agents are unavailable")
        adds["team"] = team
        adds["depth_rank"] = 0
        adds["currently_out"] = False
        players = pd.concat([players, adds], ignore_index=True)
    if traded or signed:
        strength = roster_strength.compute_unit_strength(players)
        league = sb_maxer.league_table(strength, inputs=inputs)
    report = sb_maxer.team_report(team, strength, inputs=inputs, table=league)
    return {
        "report": {**report, "needs": _records(report["needs"])},
        "league": _records(league),
        "starters": _starter_board(team, players, strength, report["needs"]),
        "signed": signed,
        "traded": traded,
        "readiness_delta": round(report["readiness"] - baseline["readiness"], 1),
        "roster_delta": round(report["roster_readiness"] - baseline["roster_readiness"], 1),
    }


@_snapshot_cache()
def _value_board() -> pd.DataFrame:
    """The value board for this DB snapshot.

    The roster refresh persists it as the ``value_board`` table (the one the
    Streamlit app reads), so serve that. Rebuilding it means parsing the raw
    contracts file: about two seconds, plus a download on a fresh container. That
    stays only as the fallback for a DB that predates the table.
    """
    if db.table_exists("value_board"):
        return db.read_table("value_board")
    return value_board.build_value_board(_player_talent())


@app.get("/api/value-board")
def value_board_data(position: str = "All", limit: int = 25) -> dict:
    """Best contract values and biggest overpays, optionally by position."""
    if not 1 <= limit <= 100:
        raise HTTPException(400, "limit must be between 1 and 100")
    try:
        board = _value_board()
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(404, "Player value data is unavailable") from exc
    positions = ["All", *sorted(board["pos_group"].dropna().unique().tolist())]
    if position not in positions:
        raise HTTPException(400, f"position must be one of {positions}")
    return {
        "positions": positions,
        "best": _records(value_board.best_values(board, pos_group=position, n=limit)),
        "worst": _records(value_board.worst_contracts(
            board, n=15, pos_group=position)),
    }


# --------------------------------------------------------------------------- #
# Film Room
# --------------------------------------------------------------------------- #
@app.get("/api/film/games")
def film_games(season: int) -> list[dict]:
    """The season's schedule (light — reads the schedule table, no play-by-play)."""
    from gridiron.ingestion import schedules
    try:
        sched = schedules.list_games(int(season))
    except Exception as exc:  # noqa: BLE001 - surface the cause to the client
        raise HTTPException(502, f"Could not load schedule: {exc}") from exc
    return _records(sched)


_PBP_CACHE: dict[int, tuple[float, pd.DataFrame]] = {}
_PBP_CACHE_TTL_SECONDS = 3600
_PBP_LOAD_LOCK = threading.Lock()


def _pbp(season: int, *, force: bool = False) -> pd.DataFrame:
    """Cache play-by-play in memory for one hour so active seasons refresh.

    Picking a game fires the summary, subtotals and plays requests together, so
    on a cold season they would each download and parse the same file. Loads are
    serialized and the cache is re-checked under the lock: the first request
    loads, the others reuse its frame. Warm reads never take the lock.
    """
    from gridiron.filmroom import pbp_metrics

    season = int(season)

    def fresh() -> pd.DataFrame | None:
        cached = _PBP_CACHE.get(season)
        if cached and time.monotonic() - cached[0] < _PBP_CACHE_TTL_SECONDS:
            return cached[1]
        return None

    if not force and (frame := fresh()) is not None:
        return frame
    with _PBP_LOAD_LOCK:
        if not force and (frame := fresh()) is not None:
            return frame
        now = time.monotonic()
        frame = pbp_metrics.load_pbp(season, force=force,
                                     ttl_hours=_PBP_CACHE_TTL_SECONDS / 3600)
        _PBP_CACHE[season] = (now, frame)
        while len(_PBP_CACHE) > 2:
            del _PBP_CACHE[next(iter(_PBP_CACHE))]
        return frame


@app.get("/api/film/summary")
def film_summary(season: int, game_id: str) -> dict:
    """The box-score payload for a game — the EPA/success numbers, no LLM call.

    Heavy on first hit for a season (loads play-by-play); cached thereafter.
    """
    from gridiron.filmroom import pbp_metrics
    pbp = _pbp(int(season))
    try:
        return pbp_metrics.build_breakdown_payload(pbp, game_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"No play-by-play for {game_id}: {exc}") from exc


@app.get("/api/film/subtotals")
def film_subtotals(season: int, game_id: str) -> dict:
    """Per-quarter running tally for a game: each offense's plays, yards, EPA,
    EPA/play and success rate, by quarter and for the whole game. Powers the Film
    Room play-by-play subtotals (the tally shown at the end of each quarter)."""
    pbp = _pbp(int(season))
    # Take only the columns the tally reads: the frame has ~370, and copying all
    # of them for one game's rows was most of this route's time.
    cols = [c for c in ("posteam", "qtr", "yards_gained", "epa", "success")
            if c in pbp.columns]
    plays = pbp.loc[(pbp["game_id"] == game_id)
                    & pbp["play_type"].isin(["pass", "run"]), cols]
    if plays.empty or not {"epa", "posteam"}.issubset(plays.columns):
        raise HTTPException(404, f"No play-by-play for {game_id}")

    def _subtotal(df: pd.DataFrame) -> list[dict[str, Any]]:
        g = df.groupby("posteam", dropna=False)
        out = pd.DataFrame({
            "plays": g.size(),
            "yards": g["yards_gained"].sum() if "yards_gained" in df else 0,
            "epa": g["epa"].sum().round(2),
            "epa_play": g["epa"].mean().round(3),
        })
        if "success" in df.columns:
            out["success"] = g["success"].mean().round(3)
        else:  # nflfastR usually ships `success`; fall back to EPA-positive rate.
            out["success"] = g["epa"].apply(lambda s: float((s > 0).mean())).round(3)
        return _records(out.reset_index().rename(columns={"posteam": "offense"}))

    def _qlabel(q: int) -> str:
        return f"Q{q}" if q <= 4 else ("OT" if q == 5 else f"OT{q - 4}")

    by_quarter: list[dict[str, Any]] = []
    if "qtr" in plays.columns:
        for q in sorted(plays["qtr"].dropna().unique()):
            qplays = plays[plays["qtr"] == q]
            by_quarter.append({"quarter": _qlabel(int(q)), "rows": _subtotal(qplays)})
    return {"game_id": game_id, "by_quarter": by_quarter, "total": _subtotal(plays)}


@app.get("/api/film/plays")
def film_plays(season: int, game_id: str) -> dict:
    """Every individual play in a game — ordered, numbered, and tagged with its
    EPA, grouped by quarter. Powers the Film Room per-play log."""
    pbp = _pbp(int(season))
    if "epa" not in pbp.columns:
        raise HTTPException(404, f"No play-by-play for {game_id}")
    # Only the columns a play row reads (of ~370), so the per-row loop below
    # handles eight values per play instead of the whole record.
    cols = [c for c in ("play_id", "order_sequence", "qtr", "posteam", "down",
                        "ydstogo", "play_type", "yards_gained", "epa", "desc")
            if c in pbp.columns]
    g = pbp.loc[pbp["game_id"] == game_id, cols]
    if g.empty:
        raise HTTPException(404, f"No play-by-play for {game_id}")
    # Real snaps only: drop the GAME marker, timeouts and penalty-only no-plays.
    g = g[g["posteam"].notna() & g["play_type"].notna() & (g["play_type"] != "no_play")]
    for col in ("play_id", "order_sequence"):
        if col in g.columns:
            g = g.sort_values(col)
            break

    def _opt(v, cast):
        return None if pd.isna(v) else cast(v)

    def _row(n: int, r: dict[str, Any]) -> dict[str, Any]:
        return {
            "n": n,
            "offense": _opt(r.get("posteam"), str),
            "down": _opt(r.get("down"), int),
            "ydstogo": _opt(r.get("ydstogo"), int),
            "play_type": _opt(r.get("play_type"), str),
            "yards": _opt(r.get("yards_gained"), int),
            "epa": _opt(r.get("epa"), lambda v: round(float(v), 2)),
            "desc": "" if pd.isna(r.get("desc")) else str(r["desc"]),
        }

    def _qlabel(q: int) -> str:
        return f"Q{q}" if q <= 4 else ("OT" if q == 5 else f"OT{q - 4}")

    by_quarter: list[dict[str, Any]] = []
    n = 0
    quarters = sorted(g["qtr"].dropna().unique()) if "qtr" in g.columns else [None]
    for q in quarters:
        qrows = g if q is None else g[g["qtr"] == q]
        plays = []
        for r in qrows.to_dict("records"):
            n += 1
            plays.append(_row(n, r))
        by_quarter.append({"quarter": "" if q is None else _qlabel(int(q)), "plays": plays})
    return {"game_id": game_id, "plays": int(n), "by_quarter": by_quarter}


@app.post("/api/film/breakdown")
def film_breakdown(body: dict) -> dict:
    """Generate the natural-language film report for a game.

    Body: ``{"season": int, "game_id": str}``. Requires ``ANTHROPIC_API_KEY``;
    returns 503 with a clear message when the key is missing.
    """
    from gridiron.filmroom import breakdown as breakdown_mod, pbp_metrics

    season, game_id = body.get("season"), body.get("game_id")
    if season is None or not game_id:
        raise HTTPException(400, "body must include `season` and `game_id`")

    pbp = _pbp(int(season))
    payload = pbp_metrics.build_breakdown_payload(pbp, game_id)
    try:
        report = breakdown_mod.generate_breakdown(payload)
    except RuntimeError as exc:  # missing ANTHROPIC_API_KEY
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Generation failed: {exc}") from exc
    return {"game_id": game_id, "report": report, "model": config.ANTHROPIC_MODEL}


# --------------------------------------------------------------------------- #
# Static frontend
#
# In production the built React SPA (``frontend/dist``) is served by this same
# app, so the whole thing ships as one Cloud Run service: one origin, no CORS.
# In development the Vite server owns the UI and ``frontend/dist`` won't exist,
# so the mount is skipped and only the JSON API runs here.
#
# This block stays at the end of the module on purpose: the catch-all route
# below must be registered *after* every ``/api/...`` route so it never shadows
# them.
# --------------------------------------------------------------------------- #
from pathlib import Path as _Path  # noqa: E402

from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

_DIST = _Path(__file__).resolve().parents[1] / "frontend" / "dist"

if _DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def _spa_index() -> FileResponse:
        return FileResponse(_DIST / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    def _spa_fallback(full_path: str) -> FileResponse:
        """Serve real static files; fall back to index.html for SPA deep links."""
        candidate = _DIST / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")
