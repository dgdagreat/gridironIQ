"""The API's performance plumbing: the per-snapshot cache, the vectorized talent
percentiles, reuse of the league inputs, and the caching/compression headers.

Nothing here needs the network. The HTTP tests read the tracked SQLite DB.
"""
from __future__ import annotations

import json
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from gridiron import api
from gridiron.filmroom import pbp_metrics
from gridiron.modeling import sb_maxer


# --------------------------------------------------------------------------- #
# _snapshot_cache
# --------------------------------------------------------------------------- #
@pytest.fixture
def stamp(monkeypatch):
    """Control the DB snapshot identity the cache keys on."""
    current = [1.0]
    monkeypatch.setattr(api, "_db_stamp", lambda: current[0])
    return current


def test_snapshot_cache_computes_once_per_snapshot(stamp):
    calls = []

    @api._snapshot_cache()
    def load():
        calls.append(1)
        return object()

    first = load()
    assert load() is first and len(calls) == 1
    stamp[0] = 2.0                       # the refresh rewrote the DB
    assert load() is not first and len(calls) == 2


def test_snapshot_cache_keys_on_arguments_and_is_bounded(stamp):
    calls = []

    @api._snapshot_cache(maxsize=2)
    def square(n):
        calls.append(n)
        return n * n

    assert [square(2), square(3), square(2)] == [4, 9, 4]
    assert calls == [2, 3]
    square(4)                            # evicts the oldest entry (2)
    square(2)
    assert calls == [2, 3, 4, 2]


def test_snapshot_cache_ttl_expires_entries(stamp):
    calls = []

    @api._snapshot_cache(ttl=0)
    def load():
        calls.append(1)

    load()
    load()
    assert len(calls) == 2


def test_snapshot_cache_does_not_cache_failures(stamp):
    calls = []

    @api._snapshot_cache()
    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("first call fails")
        return "ok"

    with pytest.raises(RuntimeError):
        flaky()
    assert flaky() == "ok" and len(calls) == 2


# --------------------------------------------------------------------------- #
# Maxer
# --------------------------------------------------------------------------- #
def test_talent_percentiles_match_the_per_player_definition():
    rng = np.random.default_rng(7)
    n = 400
    players = pd.DataFrame({
        "pos_group": rng.choice(["QB", "WR", "CB", "K", None], n),
        "talent": rng.integers(0, 40, n) / 40,          # coarse, so values tie
        "depth_rank": rng.choice([1.0, 2.0, 3.0, np.nan], n),
    })
    players.loc[rng.random(n) < 0.1, "talent"] = np.nan
    players.loc[players["pos_group"] == "K", "depth_rank"] = 2.0   # no starters

    expected = pd.Series(np.nan, index=players.index)
    for _, group in players.groupby("pos_group"):
        ref = group.loc[group["depth_rank"].eq(1), "talent"].dropna()
        if ref.empty:
            ref = group["talent"].dropna()
        for idx, value in group["talent"].items():
            if pd.notna(value):
                expected.loc[idx] = float((ref <= value).mean()) * 100

    pd.testing.assert_series_equal(api._talent_percentiles(players), expected,
                                   check_exact=True)
    assert api._talent_percentiles(players.drop(columns="talent")) is None


def test_league_table_and_report_reuse_precomputed_inputs(monkeypatch):
    positions = ["QB", "WR", "CB"]
    inputs = sb_maxer.LeagueInputs(
        weights=pd.Series([1.0, 0.6, 0.3], index=positions, name="weight"),
        org=pd.DataFrame({"team": ["AAA", "BBB"], "org_score": [90.0, 10.0]}),
        form=pd.DataFrame(),                             # pre-season: no results
    )
    strength = pd.DataFrame({
        "team": ["AAA"] * 3 + ["BBB"] * 3,
        "pos_group": positions * 2,
        "strength": [95.0, 80.0, 70.0, 20.0, 30.0, 40.0],
    })

    def unexpected():
        raise AssertionError("inputs were passed in; they must not be recomputed")

    monkeypatch.setattr(sb_maxer, "league_inputs", unexpected)
    table = sb_maxer.league_table(strength, inputs=inputs)
    assert table["team"].tolist() == ["AAA", "BBB"]
    assert table["rank"].tolist() == [1, 2]

    monkeypatch.setattr(sb_maxer, "league_table", lambda *a, **k: unexpected())
    report = sb_maxer.team_report("BBB", strength, inputs=inputs, table=table)
    assert report["rank"] == 2 and report["n_teams"] == 2
    assert report["top_needs"][0] == "QB"                # heaviest weight, biggest gap


# --------------------------------------------------------------------------- #
# Film Room
# --------------------------------------------------------------------------- #
def _synthetic_pbp() -> pd.DataFrame:
    rng = np.random.default_rng(11)
    frames = []
    for game_id, home, away in (("2030_01_AAA_BBB", "BBB", "AAA"),
                                ("2030_01_CCC_DDD", "DDD", "CCC")):
        n = 120
        play_type = rng.choice(["pass", "run", "punt"], n, p=[0.5, 0.4, 0.1])
        is_pass = play_type == "pass"
        frames.append(pd.DataFrame({
            "game_id": game_id, "week": 1, "home_team": home, "away_team": away,
            "home_score": 24, "away_score": 17,
            "posteam": rng.choice([home, away], n), "play_type": play_type,
            "qtr": rng.integers(1, 5, n), "down": rng.integers(1, 5, n),
            "drive": rng.integers(1, 12, n), "yardline_100": rng.integers(1, 100, n),
            "yards_gained": rng.integers(-5, 30, n), "epa": rng.normal(0, 1, n),
            "success": rng.integers(0, 2, n), "first_down": rng.integers(0, 2, n),
            "qb_dropback": is_pass.astype(int), "qb_hit": rng.integers(0, 2, n),
            "sack": (rng.random(n) < 0.05).astype(int),
            "interception": (rng.random(n) < 0.03).astype(int),
            "fumble_lost": (rng.random(n) < 0.02).astype(int),
            "touchdown": 0, "td_team": None, "pass_touchdown": 0, "rush_touchdown": 0,
            "complete_pass": (is_pass & (rng.random(n) < 0.6)).astype(int),
            "yards_after_catch": rng.integers(0, 15, n).astype(float),
            "passer_player_name": np.where(is_pass, "A.Passer", None),
            "rusher_player_name": np.where(play_type == "run", "B.Runner", None),
            "receiver_player_name": np.where(is_pass, "C.Catcher", None),
            "fumbled_1_player_name": "D.Fumbler",
            "not_a_metric_column": "ignored",
        }))
    return pd.concat(frames, ignore_index=True)


def test_breakdown_payload_is_unchanged_by_column_narrowing(monkeypatch):
    pbp = _synthetic_pbp()
    assert set(pbp_metrics.GAME_METRIC_COLUMNS) <= set(pbp.columns)
    narrowed = pbp_metrics.build_breakdown_payload(pbp, "2030_01_AAA_BBB")
    monkeypatch.setattr(pbp_metrics, "GAME_METRIC_COLUMNS", tuple(pbp.columns))
    full = pbp_metrics.build_breakdown_payload(pbp, "2030_01_AAA_BBB")
    assert json.dumps(narrowed, default=str) == json.dumps(full, default=str)
    assert narrowed["score"] == {"BBB": 24, "AAA": 17} and narrowed["winner"] == "BBB"


def test_concurrent_cold_requests_load_a_season_once(monkeypatch):
    """Picking a game fires three requests at once; they must share one load."""
    import threading
    import time

    loads = []

    def slow_load(season, **_):
        loads.append(season)
        time.sleep(0.2)
        return _synthetic_pbp()

    monkeypatch.setattr(pbp_metrics, "load_pbp", slow_load)
    monkeypatch.setattr(api, "_PBP_CACHE", {})
    frames = []
    threads = [threading.Thread(target=lambda: frames.append(api._pbp(2099)))
               for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert loads == [2099]
    assert len(frames) == 3 and all(f is frames[0] for f in frames)


def test_breakdown_payload_unknown_game_is_a_keyerror():
    with pytest.raises(KeyError, match="not found in play-by-play"):
        pbp_metrics.build_breakdown_payload(_synthetic_pbp(), "nope")


# --------------------------------------------------------------------------- #
# HTTP: caching and compression headers
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def client():
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    return TestClient(api.app)


def test_api_gets_are_browser_cacheable_and_gzipped(client):
    r = client.get("/api/value-board?limit=100")         # well over the gzip floor
    assert r.status_code == 200 and len(r.content) > 1024
    assert r.headers["cache-control"] == f"public, max-age={api.API_MAX_AGE_SECONDS}"
    assert r.headers["content-encoding"] == "gzip"
    assert "accept-encoding" in r.headers["vary"].lower()


def test_health_and_errors_are_not_cached(client):
    assert client.get("/api/health").headers["cache-control"] == "no-store"
    missing = client.get("/api/team-season/XXX/1900")
    assert missing.status_code == 404
    assert "cache-control" not in missing.headers


def test_importing_the_api_does_not_import_scikit_learn():
    """scikit-learn is most of the import cost; only the archetypes route needs it."""
    code = "import sys, gridiron.api; print('sklearn' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         check=True)
    assert out.stdout.strip() == "False"
