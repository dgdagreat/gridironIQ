#!/usr/bin/env python3
"""Cross-check our roster against ESPN's live feed and flag any team that drifts.

    python scripts/crosscheck_rosters.py            # print a drift report
    python scripts/crosscheck_rosters.py --store     # also write roster_crosscheck table
    python scripts/crosscheck_rosters.py --force      # re-pull rosters fresh

Runs automatically inside `refresh_rosters.py`; this is the manual/standalone view.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gridiron import db  # noqa: E402
from gridiron.ingestion.espn_roster import crosscheck_rosters  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Roster drift check vs ESPN live.")
    ap.add_argument("--store", action="store_true",
                    help="write results to the roster_crosscheck table")
    ap.add_argument("--force", action="store_true", help="re-pull rosters fresh")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s", datefmt="%H:%M:%S")

    df = crosscheck_rosters(force=args.force)
    flagged = df[df["flagged"] == 1]
    print(f"\nChecked {len(df)} teams vs ESPN live — {len(flagged)} flagged.\n")
    if flagged.empty:
        print("All rosters match ESPN's live feed ✓")
    for _, r in flagged.iterrows():
        print(f"{r['team']}  (ours {r['n_ours']} / espn {r['n_espn']})")
        if r["missing_from_ours"]:
            print(f"   ESPN has, we don't:    {r['missing_from_ours']}")
        if r["dropped_per_espn"]:
            print(f"   we list, ESPN dropped: {r['dropped_per_espn']}")

    if args.store:
        db.write_table(df, "roster_crosscheck")
        print("\nstored -> roster_crosscheck")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
