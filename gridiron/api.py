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
"""
from __future__ import annotations

import json
import time
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from gridiron import config, db
from gridiron.ingestion.reference import canonical_team
from gridiron.modeling import (cap_efficiency, clustering, roster_strength, sb_maxer,
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


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """DataFrame -> JSON-safe records.

    Round-tripping through ``df.to_json`` is the cheap way to get NaN -> null and
    numpy scalars (int64/float64) -> native JSON numbers, which plain
    ``to_dict(orient="records")`` leaves as un-serializable numpy types.
    """
    return json.loads(df.to_json(orient="records"))


# --------------------------------------------------------------------------- #
# Meta — powers the UI's season/team dropdowns
# --------------------------------------------------------------------------- #
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
    }


# --------------------------------------------------------------------------- #
# Boardroom
# --------------------------------------------------------------------------- #
@app.get("/api/champion-premium")
def champion_premium() -> list[dict]:
    """Per-position: champion cap share vs. the league, and the gap."""
    return _records(cap_efficiency.champion_premium().reset_index())


@app.get("/api/efficiency-verdict")
def efficiency_verdict() -> list[dict]:
    """Premium + spend/win correlation rolled into a per-position verdict."""
    return _records(cap_efficiency.efficiency_verdict().reset_index())


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
    return {
        "team": team,
        "season": season,
        "positions": _records(positions),
        "players": _records(players),
    }


@app.get("/api/archetypes")
def archetypes(k: int = 5) -> dict:
    """K-means spending archetypes with each cluster's SB success rate."""
    if not 2 <= k <= 10:
        raise HTTPException(400, "k must be between 2 and 10")
    res = clustering.cluster_archetypes(k=k)
    success = res.success.join(res.profiles["label"]).reset_index()
    return {
        "k": k,
        "success": _records(success),
        "profiles": _records(res.profiles.reset_index()),
    }


# --------------------------------------------------------------------------- #
# Super Bowl Maxer + Value Board
# --------------------------------------------------------------------------- #
def _player_talent() -> pd.DataFrame:
    return db.read_table("player_talent")


def _roster_strength() -> pd.DataFrame:
    return db.read_table("roster_strength")


@app.get("/api/maxer/{team}")
def maxer(team: str) -> dict:
    """Team outlook, needs, available free agents and trade targets."""
    try:
        strength = _roster_strength()
        report = sb_maxer.team_report(team, strength)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(404, f"No roster data for {team}") from exc
    players = _player_talent()
    needs = report["top_needs"]
    if db.table_exists("free_agents"):
        fa = db.read_table("free_agents")
        need_order = {pos: idx for idx, pos in enumerate(needs)}
        fa = fa.assign(_need=fa["pos_group"].map(need_order).fillna(99))
        fa = fa.sort_values(["_need", "talent"], ascending=[True, False]).head(30)
        fa = fa[[c for c in ("player", "pos_group", "age", "madden_ovr", "talent", "est_apy")
                 if c in fa.columns]]
    else:
        fa = pd.DataFrame()
    targets = trade_market.trade_board(players, team, needs, per_need=6)
    league = sb_maxer.league_table(strength)
    report["needs"] = _records(report["needs"])
    starters = _starter_board(team, players, strength)
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


def _starter_board(team: str, players: pd.DataFrame,
                   strength: pd.DataFrame) -> list[dict[str, Any]]:
    """Assign likely starters to the same 11-personnel vs nickel field as Streamlit."""
    pool = players[players["team"] == team].copy()
    if "talent" in players:
        players = players.copy()
        players["_starter"] = (players["depth_rank"].eq(1)
                               if "depth_rank" in players else True)
        players["talent_pct"] = float("nan")
        for _, group in players.groupby("pos_group"):
            ref = group.loc[group["_starter"], "talent"].dropna()
            if ref.empty:
                ref = group["talent"].dropna()
            players.loc[group.index, "talent_pct"] = group["talent"].rank(pct=True).mul(100)
            if not ref.empty:
                # Use the starter pool as the comparison population, as in Streamlit.
                players.loc[group.index, "talent_pct"] = group["talent"].apply(
                    lambda value: float((ref <= value).mean()) * 100 if pd.notna(value) else float("nan"))
        pool = players[players["team"] == team].copy()
    pool["_out"] = (pool["currently_out"].fillna(False).astype(bool)
                    if "currently_out" in pool else False)
    sort_cols, ascending = ["_out"], [True]
    if "depth_rank" in pool:
        sort_cols.append("depth_rank"); ascending.append(True)
    for col, direction in (("madden_ovr", False), ("talent", False)):
        if col in pool:
            sort_cols.append(col); ascending.append(direction)
    needs = sb_maxer.team_report(team, strength)["needs"].set_index("pos_group")
    ranked = strength.assign(
        rank=strength.groupby("pos_group")["strength"].rank(ascending=False, method="min"))
    team_rank = ranked[ranked["team"] == team].set_index("pos_group")["rank"]
    n_teams = int(strength["team"].nunique())
    used: set[Any] = set()
    out: list[dict[str, Any]] = []
    for label, pos, x, y, bucket in _FORMATION:
        group = pool[pool["pos_group"] == pos].sort_values(
            sort_cols, ascending=ascending, na_position="last")
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
        baseline = sb_maxer.team_report(team, strength)
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
        if not db.table_exists("free_agents"):
            raise HTTPException(404, "Free-agent data is unavailable")
        fa = db.read_table("free_agents")
        adds = fa[fa["player"].isin(signed)].copy()
        if len(adds) != len(signed):
            raise HTTPException(400, "One or more selected free agents are unavailable")
        adds["team"] = team
        adds["depth_rank"] = 0
        adds["currently_out"] = False
        players = pd.concat([players, adds], ignore_index=True)
    if traded or signed:
        strength = roster_strength.compute_unit_strength(players)
    report = sb_maxer.team_report(team, strength)
    league = sb_maxer.league_table(strength)
    return {
        "report": {**report, "needs": _records(report["needs"])},
        "league": _records(league),
        "starters": _starter_board(team, players, strength),
        "signed": signed,
        "traded": traded,
        "readiness_delta": round(report["readiness"] - baseline["readiness"], 1),
        "roster_delta": round(report["roster_readiness"] - baseline["roster_readiness"], 1),
    }


_VALUE_BOARD_CACHE: tuple[float, pd.DataFrame] | None = None


def _value_board() -> pd.DataFrame:
    """Build the value board once per DB snapshot, keyed on the DB file's mtime.

    ``build_value_board`` scans all player value data (a few seconds); the
    position filter is applied afterward, so the board is reused across requests
    until the daily DB refresh changes the file's mtime.
    """
    global _VALUE_BOARD_CACHE
    try:
        mtime = config.DB_PATH.stat().st_mtime
    except OSError:
        mtime = 0.0
    if _VALUE_BOARD_CACHE is None or _VALUE_BOARD_CACHE[0] != mtime:
        _VALUE_BOARD_CACHE = (mtime, value_board.build_value_board(_player_talent()))
    return _VALUE_BOARD_CACHE[1]


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


def _pbp(season: int, *, force: bool = False) -> pd.DataFrame:
    """Cache play-by-play in memory for one hour so active seasons refresh."""
    from gridiron.filmroom import pbp_metrics

    now = time.monotonic()
    cached = _PBP_CACHE.get(int(season))
    if not force and cached and now - cached[0] < _PBP_CACHE_TTL_SECONDS:
        return cached[1]
    frame = pbp_metrics.load_pbp(int(season), force=force,
                                 ttl_hours=_PBP_CACHE_TTL_SECONDS / 3600)
    _PBP_CACHE[int(season)] = (now, frame)
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
