#!/usr/bin/env python3
"""Refresh the Super Bowl Maxer data layer: rosters + talent → strength → SQLite.

Built to run on a schedule so the roster stays fresh as the NFL churns. The cap
ETL (`run_cap_etl.py`) must have run once first — the Maxer reuses the Boardroom's
position-importance weights.

Usage:
    python scripts/refresh_rosters.py            # uses 24h download cache
    python scripts/refresh_rosters.py --force    # bypass cache (always fresh)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from gridiron import db  # noqa: E402
from gridiron.ingestion.rosters import (  # noqa: E402
    build_free_agent_pool, build_player_talent)
from gridiron.modeling import free_agents  # noqa: E402
from gridiron.modeling.roster_strength import (  # noqa: E402
    compute_unit_strength, player_talent_scores)
from gridiron.modeling.sb_maxer import league_table  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh Super Bowl Maxer data.")
    ap.add_argument("--season", type=int, default=None,
                    help="League year (default: current).")
    ap.add_argument("--force", action="store_true",
                    help="Bypass download caches and re-fetch.")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    if not db.table_exists("spending_features"):
        print("ERROR: cap data not loaded. Run `python scripts/run_cap_etl.py` first.")
        return 1

    players, meta = build_player_talent(args.season, force=args.force)
    strength = compute_unit_strength(players)
    league = league_table(strength)

    # Available free agents (last season's players not on a current roster).
    fa_raw, fa_meta = build_free_agent_pool(args.season, force=args.force)
    free_agent_pool = free_agents.score_pool(fa_raw)
    meta["n_free_agents"] = fa_meta["n_free_agents"]

    # Store the scored players (with age/trend breakdown) for transparency.
    db.write_table(player_talent_scores(players), "player_talent")
    db.write_table(strength, "roster_strength")
    db.write_table(league, "maxer_league")
    db.write_table(free_agent_pool, "free_agents")
    db.write_table(pd.DataFrame([meta]), "maxer_meta")

    print("\n" + "=" * 56)
    print(" Super Bowl Maxer — refresh complete")
    print("=" * 56)
    for k, v in meta.items():
        print(f"  {k:16} {v}")
    print("-" * 56)
    print("  Closest to a champion roster:")
    for _, r in league.head(5).iterrows():
        print(f"    {r['rank']:>2}. {r['team']:<4} readiness {r['readiness']}")
    print("  Furthest:")
    for _, r in league.tail(3).iterrows():
        print(f"    {r['rank']:>2}. {r['team']:<4} readiness {r['readiness']}")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
