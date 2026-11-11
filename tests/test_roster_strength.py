"""``compute_unit_strength`` picks every unit's starters in one vectorized pass.

The straightforward version (one filter + sort per team x position) is kept here as
the reference, and the two must agree exactly on rosters that exercise the awkward
cases: whole units ruled out, missing depth ranks, unrated players, tied talents,
positions with no configured unit size, and rows with no team or position.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from gridiron.modeling import roster_strength
from gridiron.modeling.roster_strength import (
    STAR_WEIGHT,
    UNIT_SIZE,
    UNRATED_TALENT,
    compute_unit_strength,
    player_talent_scores,
)


def _reference_unit_strength(players: pd.DataFrame) -> pd.DataFrame:
    """The per-group implementation ``compute_unit_strength`` replaced."""
    scored = player_talent_scores(players)
    for col, dflt in (("depth_rank", pd.NA), ("currently_out", False)):
        if col not in scored:
            scored[col] = dflt
    out_now = scored["currently_out"].fillna(False).astype(bool)

    rows: list[dict] = []
    for (team, pos), grp in scored.groupby(["team", "pos_group"]):
        k = UNIT_SIZE.get(pos, 3)
        avail = grp[~out_now.loc[grp.index]]
        pool = avail if not avail.empty else grp
        top = pool.sort_values(["depth_rank", "talent"], ascending=[True, False],
                               na_position="last").head(k)
        t = top["talent"].sort_values(ascending=False)
        unit = (STAR_WEIGHT * float(t.iloc[0]) + (1 - STAR_WEIGHT) * float(t.mean())
                if len(t) else UNRATED_TALENT)
        rows.append({
            "team": team,
            "pos_group": pos,
            "unit_score": round(unit, 4),
            "n_players": len(pool),
            "top_player": top.loc[top["talent"].idxmax(), "player"] if len(top) else None,
        })
    units = pd.DataFrame(rows)
    units["strength"] = (
        units.groupby("pos_group")["unit_score"].rank(pct=True) * 100
    ).round(1)
    return units.sort_values(["team", "pos_group"], ignore_index=True)


def _roster(seed: int, n: int = 900) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    teams = [f"T{i:02d}" for i in range(12)]
    positions = [*UNIT_SIZE, "XX"]                  # XX has no configured unit size
    df = pd.DataFrame({
        "player": [f"P{i}" for i in range(n)],
        "team": rng.choice(teams, n),
        "pos_group": rng.choice(positions, n),
        # Coarse ratings so talents tie often, which is what stresses the ordering.
        "madden_ovr": rng.integers(60, 99, n).astype(float),
        "last_av": rng.integers(0, 18, n).astype(float),
        "age": rng.integers(21, 38, n).astype(float),
        "depth_rank": rng.choice([1.0, 1.0, 2.0, 3.0, np.nan], n),
        "currently_out": rng.random(n) < 0.25,
    })
    df.loc[rng.random(n) < 0.15, ["madden_ovr", "last_av"]] = np.nan   # unrated
    df.loc[rng.random(n) < 0.02, "team"] = None
    df.loc[rng.random(n) < 0.02, "pos_group"] = None
    # A whole unit on the injury report must fall back to grading everyone in it.
    df.loc[(df["team"] == "T00") & (df["pos_group"] == "QB"), "currently_out"] = True
    return df


@pytest.mark.parametrize("seed", range(8))
def test_matches_reference_on_random_rosters(seed):
    players = _roster(seed)
    pd.testing.assert_frame_equal(compute_unit_strength(players),
                                  _reference_unit_strength(players), check_exact=True)


def test_matches_reference_without_optional_columns():
    players = _roster(99).drop(columns=["depth_rank", "currently_out"])
    pd.testing.assert_frame_equal(compute_unit_strength(players),
                                  _reference_unit_strength(players), check_exact=True)


def test_unit_out_entirely_still_grades():
    players = _roster(3)
    units = compute_unit_strength(players).set_index(["team", "pos_group"])
    qbs = players[(players["team"] == "T00") & (players["pos_group"] == "QB")]
    assert len(qbs) > 0 and qbs["currently_out"].all()
    assert units.loc[("T00", "QB"), "n_players"] == len(qbs)


def test_ruled_out_star_does_not_carry_the_unit():
    players = pd.DataFrame({
        "player": ["Star", "Backup", "Other"],
        "team": ["AAA", "AAA", "BBB"],
        "pos_group": ["QB", "QB", "QB"],
        "madden_ovr": [99.0, 70.0, 85.0],
        "depth_rank": [1.0, 2.0, 1.0],
        "currently_out": [True, False, False],
    })
    units = compute_unit_strength(players).set_index("team")
    assert units.loc["AAA", "top_player"] == "Backup"
    assert units.loc["AAA", "n_players"] == 1
    assert roster_strength.UNIT_SIZE["QB"] == 1
