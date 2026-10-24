#!/usr/bin/env python3
"""Train the player-value model and report it (CV metrics + feature importance),
then print the current season's top projected players.

Usage:
    PYTHONPATH=. python scripts/train_player_value.py
    PYTHONPATH=. python scripts/train_player_value.py --season 2026 --week 6
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gridiron import config  # noqa: E402
from gridiron.modeling import player_value as pv  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Train + report the player-value model.")
    ap.add_argument("--season", type=int, default=config.CURRENT_SEASON,
                    help="Season to project (default: current).")
    ap.add_argument("--week", type=int, default=None,
                    help="Project from form through this week (default: latest played).")
    ap.add_argument("--top", type=int, default=15, help="How many to list.")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

    rep = pv.train_value_model()
    print("\n" + "=" * 60)
    print(" Player-value model — training report")
    print("=" * 60)
    print(f"  samples            {rep.n_samples}")
    print(f"  baseline R2        {rep.baseline_r2:.3f}   (rest-of-season = recent form)")
    print(f"  model R2 (5-fold)  {rep.cv_r2_mean:.3f} ± {rep.cv_r2_std:.3f}")
    print(f"  model MAE          {rep.cv_mae:.2f}   fantasy pts/game")
    print("  feature importance (permutation, drop in R2):")
    for name, val in rep.feature_importance:
        tag = "   <- highlight plays" if name == "expl_g" else ""
        print(f"    {name:12} {val:.4f}{tag}")

    week = args.week
    if week is None:
        try:
            w = pv.load_weekly_stats(args.season)
            week = int(w[w.get("season_type", "REG").eq("REG")]["week"].max())
        except Exception:  # noqa: BLE001
            week = 6
    vals = pv.predict_values(rep, args.season, as_of_week=week)
    print("-" * 60)
    print(f"  Top {args.top} projected values — {args.season} through week {week} "
          f"(rest-of-season fantasy pts/game):")
    for r in vals.head(args.top).itertuples(index=False):
        print(f"    {r.value:6.2f}  {r.player:<22} {r.position:<3} {r.team}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
