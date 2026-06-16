#!/usr/bin/env python3
"""Generate a Film Room report for any game — pre- or post-game — by game_id.

    python scripts/run_filmroom.py 2025_22_SEA_NE      # played   -> post-game breakdown
    python scripts/run_filmroom.py 2026_01_NE_SEA      # scheduled-> pre-game preview
    python scripts/run_filmroom.py 2025_22_SEA_NE --payload-only   # metrics only, no API call

The report step needs ANTHROPIC_API_KEY (in .env or the environment);
`--payload-only` prints the extracted metrics and skips the API entirely.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gridiron import db  # noqa: E402
from gridiron.filmroom import breakdown, matchup, pbp_metrics  # noqa: E402
from gridiron.ingestion import schedules  # noqa: E402


def build_payload(game_id: str) -> dict:
    """Route by schedule status: played -> post-game, scheduled -> pre-game."""
    game = schedules.get_game(game_id)
    season = int(game_id.split("_")[0])
    if game["status"] == "played":
        pbp = pbp_metrics.load_pbp(season)
        return pbp_metrics.build_breakdown_payload(pbp, game_id)
    form_season = season - 1   # offseason: last completed season's form
    form_pbp = pbp_metrics.load_pbp(form_season)
    strength = db.read_table("roster_strength") if db.table_exists("roster_strength") else None
    return matchup.build_preview_payload(
        game["home_team"], game["away_team"], form_pbp=form_pbp,
        form_season=form_season, week=int(game["week"]), roster_strength=strength)


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate a Film Room report by game_id.")
    ap.add_argument("game_id", help="e.g. 2025_22_SEA_NE (played) or 2026_01_NE_SEA (scheduled)")
    ap.add_argument("--payload-only", action="store_true",
                    help="Print the extracted metrics and skip the API call.")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s", datefmt="%H:%M:%S")

    payload = build_payload(args.game_id)
    print(f"\n=== {args.game_id}  ({payload['mode']}-game) ===\n")
    if args.payload_only:
        print(json.dumps(payload, indent=2, default=str))
        return 0
    try:
        print(breakdown.generate_breakdown(payload))
    except RuntimeError as exc:           # missing key, etc.
        print(f"Cannot generate the report: {exc}")
        print("Tip: re-run with --payload-only to see the metrics without the API.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
