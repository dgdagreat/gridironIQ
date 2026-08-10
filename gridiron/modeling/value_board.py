"""
Value board -- the most cap-efficient players in football.

Crosses each player's Madden rating (a clean, well-calibrated 0--99 caliber
signal) with his real contract APY (OverTheCap, via :func:`cap_data.latest_apy`).
Rather than invent a contestable dollar "market value", we compare two
percentiles *within a position*:

    value_index = caliber_pct - pay_pct

A top-5%-caliber receiver paid in the bottom-5% at his position scores about +80
-- elite value (Puka Nacua on his rookie deal); a middling veteran on
top-of-market money scores deeply negative -- a bad contract (a 75-OVR QB at
$55M). It's unit-free, position-relative, and robust to the cheap rookie deals
that break a dollar-denominated model.

We deliberately use *raw* Madden here (not the age/trend-adjusted talent score the
Maxer uses): the talent score saturates at 1.0 for ~100 players, which scrambles
a value ranking, whereas Madden keeps its spread. A Madden floor drops fringe
roster fillers so the board stays credible.
"""

from __future__ import annotations

import pandas as pd

from gridiron.ingestion import cap_data

#: A "bargain" has to be an actual contributor: a real deal (not vet-minimum
#: noise) and a real rating (not a camp body) at both ends.
MIN_APY_M = 0.5
MIN_OVR = 75

#: Caliber-percentile -> letter grade (same scale the rest of the app uses).
_GRADE_BANDS = ((85, "A"), (70, "B"), (45, "C"), (25, "D"), (0, "F"))


def _grade(pctile: float) -> str:
    for lo, g in _GRADE_BANDS:
        if pctile >= lo:
            return g
    return "F"


def _stars(value_index: float) -> int:
    """value_index (roughly -100..+100) -> a 1--5 star value rating."""
    return (5 if value_index >= 50 else 4 if value_index >= 25
            else 3 if value_index >= 0 else 2 if value_index >= -25 else 1)


def build_value_board(players: pd.DataFrame) -> pd.DataFrame:
    """Score every rostered player's contract value.

    ``players`` is the ``player_talent`` table (needs ``gsis_id, player, team,
    pos_group, age, madden_ovr``). Returns one row per eligible player with
    ``apy, caliber_pct, pay_pct, grade, value_index, value`` (1--5 stars), sorted
    best-value first.
    """
    df = players.copy()
    df["apy"] = df["gsis_id"].map(cap_data.latest_apy())
    df = df[df["apy"].notna() & (df["apy"] >= MIN_APY_M)
            & df["madden_ovr"].notna() & (df["madden_ovr"] >= MIN_OVR)].copy()

    # Caliber and pay percentiles *within* the position group (0--100).
    df["caliber_pct"] = df.groupby("pos_group")["madden_ovr"].rank(pct=True).mul(100)
    df["pay_pct"] = df.groupby("pos_group")["apy"].rank(pct=True).mul(100)
    df["grade"] = df["caliber_pct"].map(_grade)

    # Value = how far a player's caliber outruns his pay (both position-relative).
    df["value_index"] = (df["caliber_pct"] - df["pay_pct"]).round(0).astype(int)
    df["value"] = df["value_index"].map(_stars)

    df["apy"] = df["apy"].round(1)
    for col in ("caliber_pct", "pay_pct"):
        df[col] = df[col].round(0).astype(int)

    cols = ["player", "team", "pos_group", "age", "madden_ovr", "grade",
            "caliber_pct", "pay_pct", "apy", "value_index", "value"]
    cols = [c for c in cols if c in df.columns]
    return df[cols].sort_values("value_index", ascending=False, ignore_index=True)


def best_values(board: pd.DataFrame, *, pos_group: str | None = None,
                n: int = 25) -> pd.DataFrame:
    """Top value-index players, optionally filtered to one position."""
    b = board if not pos_group or pos_group == "All" \
        else board[board["pos_group"] == pos_group]
    return b.head(n).reset_index(drop=True)


def worst_contracts(board: pd.DataFrame, *, min_pay_pct: float = 50.0,
                    n: int = 15) -> pd.DataFrame:
    """Biggest overpays -- well-paid players (top-half money) delivering least."""
    b = board[board["pay_pct"] >= min_pay_pct]
    return b.sort_values("value_index").head(n).reset_index(drop=True)


if __name__ == "__main__":  # demo (needs the roster refresh to have run)
    from gridiron import db
    pd.set_option("display.width", 170)
    board = build_value_board(db.read_table("player_talent"))
    print("=== Best values in football (caliber vs. pay) ===")
    print(best_values(board, n=15).to_string(index=False))
    print("\n=== Worst contracts ===")
    print(worst_contracts(board, n=10).to_string(index=False))
