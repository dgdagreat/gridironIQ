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
from functools import lru_cache
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from gridiron import config, db
from gridiron.modeling import cap_efficiency, clustering

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
@lru_cache(maxsize=1)
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


@lru_cache(maxsize=2)
def _pbp(season: int) -> pd.DataFrame:
    """Load a season's play-by-play once (~40 MB) and keep it in process."""
    from gridiron.filmroom import pbp_metrics
    return pbp_metrics.load_pbp(int(season))


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
