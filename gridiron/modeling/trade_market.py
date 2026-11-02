"""
Trade market: estimate what a rostered player would cost to acquire in a trade,
expressed in **draft-pick** terms.

v1 values a player from his on-field caliber (``talent``), his age (future value)
and a positional market premium, then maps that value onto the Jimmy Johnson
draft-pick value chart to name the rough pick it would take. This is an
analytical estimate, not a live market: it does **not** model the player's
contract/cap, the other team's willingness to deal, scheme fit, or the picks the
acquiring side sends out. Contract value is the obvious v2 input.

The positional premium here is deliberately the *trade market's* ordering (QB at
the top, specialists at the bottom) — distinct from the Boardroom's
cap-efficiency weights, which rank tight end highest for a different reason.
"""

from __future__ import annotations

import pandas as pd

#: Positional market premium for trade value. QB commands the market; edge,
#: receiver, tackle and corner carry a premium; specialists bring up the rear.
TRADE_POS_MULT: dict[str, float] = {
    "QB": 1.60, "EDGE": 1.25, "WR": 1.20, "T": 1.15, "G": 1.15, "C": 1.15, "OL": 1.15, "CB": 1.15,
    "IDL": 1.05, "S": 0.95, "TE": 0.90, "LB": 0.80, "RB": 0.70, "SPEC": 0.40,
}
_MAX_MULT = 1.60
_DEFAULT_MULT = 0.70

#: Jimmy Johnson draft-pick value chart, sampled at anchor picks and linearly
#: interpolated between them. overall pick -> value points (pick 1 = 3000).
_JJ: list[tuple[int, float]] = [
    (1, 3000), (2, 2600), (3, 2200), (5, 1700), (10, 1300), (15, 1050),
    (20, 850), (25, 720), (32, 590), (40, 500), (50, 400), (64, 270),
    (75, 215), (96, 116), (128, 44), (160, 27), (192, 15), (224, 4), (256, 2),
]


def age_factor(age: float | None) -> float:
    """Future-value multiplier: young players are worth more in a trade, older
    ones less, because the pick you give up is a multi-year asset."""
    if age is None or pd.isna(age):
        return 0.90
    a = float(age)
    if a <= 24:
        return 1.15
    if a <= 27:
        return 1.00
    if a <= 29:
        return 0.85
    if a <= 31:
        return 0.65
    return 0.45


def _talent_base(talent: pd.Series) -> pd.Series:
    """Convex caliber curve on ``talent`` (0–1): replacement level (~0.35) is
    worth nothing, and value ramps steeply toward the stars."""
    t = pd.to_numeric(talent, errors="coerce")
    return (((t - 0.35).clip(lower=0, upper=0.65) / 0.65) ** 2.2).fillna(0.0)


def value_points(players: pd.DataFrame) -> pd.DataFrame:
    """Add ``trade_pts`` (0–3000, Jimmy-Johnson units) to a players frame."""
    df = players.copy()
    mult = df["pos_group"].map(TRADE_POS_MULT).fillna(_DEFAULT_MULT) / _MAX_MULT
    agef = (df["age"].map(age_factor) if "age" in df.columns
            else pd.Series(1.0, index=df.index))
    df["trade_pts"] = (3000 * _talent_base(df["talent"]) * mult * agef
                       ).clip(0, 3000).round(0)
    return df


def _pts_to_pick(pts: float) -> int:
    """Approximate overall pick whose chart value this many points buys."""
    for pick, val in _JJ:
        if pts >= val:
            return pick
    return 256


def pick_tier(pts: float) -> str:
    """Human label for a trade-value points total, in draft-pick terms."""
    if pts >= 2000:
        return "1st round (top-10)"
    if pts >= 1000:
        return "1st round (mid)"
    if pts >= 650:
        return "late 1st / early 2nd"
    if pts >= 380:
        return "2nd round"
    if pts >= 190:
        return "3rd round"
    if pts >= 80:
        return "Day 3 (4th–5th)"
    if pts >= 20:
        return "late Day 3 (6th–7th)"
    return "minimal (flier)"


def estimate(players: pd.DataFrame) -> pd.DataFrame:
    """Add ``trade_pts``, ``est_pick`` (overall), ``est_round`` and ``pick_tier``."""
    df = value_points(players)
    df["est_pick"] = df["trade_pts"].map(_pts_to_pick)
    df["est_round"] = (((df["est_pick"] - 1) // 32) + 1).clip(upper=7).astype(int)
    df["pick_tier"] = df["trade_pts"].map(pick_tier)
    return df


def trade_board(players: pd.DataFrame, team: str, needs: list[str],
                per_need: int = 5) -> pd.DataFrame:
    """Best **acquirable** players (on other rosters) at the team's need
    positions, ranked by talent, with trade-value estimates. ``needs`` is the
    ordered list of position groups (biggest hole first)."""
    pool = players[(players["team"] != team)].copy()
    if "currently_out" in pool.columns:
        pool = pool[~pool["currently_out"].fillna(False).astype(bool)]
    pool = estimate(pool)
    frames = [pool[pool["pos_group"] == pos].nlargest(per_need, "talent")
              for pos in needs]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    cols = ["gsis_id", "player", "team", "pos_group", "age", "madden_ovr",
            "talent", "trade_pts", "est_round", "pick_tier"]
    out = pd.concat(frames, ignore_index=True)
    return out[[c for c in cols if c in out.columns]]


if __name__ == "__main__":  # quick smoke test
    from gridiron import db
    pt = db.read_table("player_talent")
    est = estimate(pt).sort_values("trade_pts", ascending=False)
    pd.set_option("display.width", 160)
    print("Top trade values leaguewide:")
    print(est[["player", "team", "pos_group", "age", "talent", "trade_pts",
               "pick_tier"]].head(15).to_string(index=False))
