"""
Roster strength: turn per-player talent into per-team, per-position rankings.

  player talent (production + external grade)
    → per-player talent score (percentile within position group)
      → per-team unit score (quality of the starters at each position)
        → strength percentile vs. the 32 teams (0–100)

The output is "how does this team's QB room / O-line / secondary rank against
the league," which is the axis the Super Bowl Maxer measures gaps on.
"""

from __future__ import annotations

import pandas as pd

#: How many players define a "unit" at each position (starters + key rotation).
UNIT_SIZE: dict[str, int] = {
    "QB": 1, "RB": 2, "WR": 4, "TE": 2, "OL": 5, "IDL": 4,
    "EDGE": 4, "LB": 4, "CB": 4, "S": 3, "SPEC": 3,
}
#: Talent baseline for unrated players (rookies/UDFAs with no grade yet).
UNRATED_TALENT = 0.25

# --- Age decline is position-specific: a static rating is not destiny, and
# positions don't age alike. A running back falls off a cliff in his late 20s; a
# QB, O-lineman, or specialist ages gracefully. Each position gets its own
# (peak age, decline per year past peak, floor) curve. ------------------------
AGE_CURVE: dict[str, tuple[float, float, float]] = {
    # pos:    (peak, decline/yr, floor)   -- football aging reality
    "QB":   (33, 0.020, 0.70),   # ages best — can stay elite into late 30s
    "RB":   (26, 0.070, 0.40),   # earliest + steepest cliff
    "WR":   (27, 0.045, 0.55),
    "TE":   (28, 0.045, 0.55),
    "OL":   (29, 0.030, 0.60),   # durable; technique outlasts athleticism
    "IDL":  (28, 0.040, 0.55),
    "EDGE": (28, 0.050, 0.50),   # bend/burst fade with age
    "LB":   (27, 0.055, 0.50),   # speed-dependent
    "CB":   (28, 0.060, 0.45),   # speed cliff hits hard
    "S":    (29, 0.045, 0.55),   # ages a touch better than CB
    "SPEC": (35, 0.010, 0.85),   # kickers/punters barely age
}
_DEFAULT_CURVE = (29, 0.040, 0.55)

# --- Production trend: reward ascending players, only lightly mark down
# decliners (AV is noisy year to year; a small dip shouldn't tank a star). ------
TREND_SENSITIVITY = 0.5
TREND_MIN, TREND_MAX = 0.97, 1.15


def age_factor(pos_group: str, age: float | None) -> float:
    """Position-specific age multiplier (≤1): RBs decline fast, QBs/kickers slow."""
    if age is None or pd.isna(age):
        return 1.0
    peak, decline, floor = AGE_CURVE.get(pos_group, _DEFAULT_CURVE)
    if age <= peak:
        return 1.0
    return max(floor, 1.0 - decline * (age - peak))


def trend_factor(av0: float | None, av1: float | None, av2: float | None) -> float:
    """Multiplier from recent production vs. the prior 1–2 seasons.

    >1 for rising players, <1 for decliners; neutral (1.0) without enough history.
    """
    priors = [v for v in (av1, av2) if pd.notna(v)]
    if pd.isna(av0) or not priors:
        return 1.0
    baseline = sum(priors) / len(priors)
    if baseline <= 0:
        return TREND_MAX if (av0 or 0) > 0 else 1.0
    ratio = av0 / baseline
    return min(TREND_MAX, max(TREND_MIN, 1.0 + TREND_SENSITIVITY * (ratio - 1)))


#: Below this many games in the season its AV reflects, a player's production is
#: treated as injury-shortened (a full season is 17) — see player_talent_scores.
INJURY_GP_MAX = 8


def player_talent_scores(players: pd.DataFrame) -> pd.DataFrame:
    """Add a 0–1 ``talent`` score per player (mean of available signals).

    Each signal (Madden overall = external grade, AV = production) is
    percentile-ranked *within its position group*, then averaged per player;
    unrated players fall back to :data:`UNRATED_TALENT`.

    **Coming off injury:** if the season a player's AV reflects was
    injury-shortened (``games_av0`` below :data:`INJURY_GP_MAX`), that AV
    understates him — so he is scored on his best recent *healthy* season instead,
    and the production-trend penalty is waived (a missed year isn't a decline).
    Needs the games feed from ``ingestion.rosters.build_player_talent``; without
    ``games_av0`` nobody is flagged and scoring is unchanged.
    """
    df = players.copy()
    for col in ("madden_ovr", "last_av", "age", "av0", "av1", "av2", "games_av0"):
        if col not in df:
            df[col] = pd.NA

    # Injury guard: a low games total in the AV's own season means missed time.
    gp = pd.to_numeric(df["games_av0"], errors="coerce")
    injured = gp.notna() & (gp < INJURY_GP_MAX)
    healthy_av = df[["av0", "av1", "av2"]].apply(
        pd.to_numeric, errors="coerce").max(axis=1)
    # Score injured players on their best recent (healthy) production, not the dip.
    df["last_av_eff"] = df["last_av"].where(~injured, healthy_av)
    df["injured_last"] = injured

    df["madden_ovr_pct"] = df.groupby("pos_group")["madden_ovr"].rank(pct=True)
    df["last_av_pct"] = df.groupby("pos_group")["last_av_eff"].rank(pct=True)

    # Static talent = external grade (Madden) weighted over production (AV).
    # Madden leads because AV is a noisy, team-dependent counting stat that
    # compresses elite players; AV still informs grades where Madden is
    # missing or soft. Fall back to whichever signal exists.
    _m, _a = df["madden_ovr_pct"], df["last_av_pct"]
    df["talent_static"] = ((0.8 * _m + 0.2 * _a)
                           .fillna(_m).fillna(_a).fillna(UNRATED_TALENT))
    # Adjust the static grade for age and production trend — a rating isn't gospel.
    df["age_factor"] = [age_factor(p, a) for p, a in zip(df["pos_group"], df["age"])]
    df["trend_factor"] = [
        trend_factor(a0, a1, a2)
        for a0, a1, a2 in zip(df["av0"], df["av1"], df["av2"])
    ]
    # A missed season is not a decline — waive the trend penalty for injured players.
    df.loc[injured, "trend_factor"] = df.loc[injured, "trend_factor"].clip(lower=1.0)
    df["talent"] = (df["talent_static"] * df["age_factor"] * df["trend_factor"]).clip(0, 1)
    return df


def compute_unit_strength(players: pd.DataFrame) -> pd.DataFrame:
    """Aggregate to one row per team × position group with a 0–100 strength.

    Columns: team, pos_group, unit_score (raw starter quality), strength
    (percentile vs. the league), n_players, top_player.
    """
    scored = player_talent_scores(players)

    rows: list[dict] = []
    for (team, pos), grp in scored.groupby(["team", "pos_group"]):
        k = UNIT_SIZE.get(pos, 3)
        top = grp.nlargest(k, "talent")
        t = top["talent"]
        # Star-weighted: the best player carries the unit (an elite anchor like a
        # top QB or interior lineman shouldn't grade out poorly just because the
        # depth behind him is thin), tempered by the quality of that depth.
        unit = (0.75 * float(t.iloc[0]) + 0.25 * float(t.mean())
                if len(t) else UNRATED_TALENT)
        rows.append({
            "team": team,
            "pos_group": pos,
            "unit_score": round(unit, 4),
            "n_players": int(len(grp)),
            "top_player": top.iloc[0]["player"] if len(top) else None,
        })
    units = pd.DataFrame(rows)

    # Strength = percentile of the unit vs. the 32 teams, within position group.
    units["strength"] = (
        units.groupby("pos_group")["unit_score"].rank(pct=True) * 100
    ).round(1)
    return units.sort_values(["team", "pos_group"], ignore_index=True)
