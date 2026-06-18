#!/usr/bin/env python3
"""Generate Film Room reports — pre- or post-game — for one game or a whole week.

    # one game (auto-routes pre/post by schedule status)
    python scripts/run_filmroom.py 2025_22_SEA_NE
    python scripts/run_filmroom.py 2026_01_NE_SEA
    python scripts/run_filmroom.py 2025_22_SEA_NE --payload-only   # metrics, no API call

    # a whole week -> writes one markdown file (reports/ is gitignored)
    python scripts/run_filmroom.py --season 2026 --week 1
    python scripts/run_filmroom.py --season 2026 --week 1 --out reports/wk1.md

The report step needs ANTHROPIC_API_KEY (in .env or the environment).
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


def _run_week(season: int, week: int, out: str | None) -> int:
    """Generate every game in a week into one markdown file."""
    games = schedules.list_games(season, week)
    out_path = Path(out) if out else Path("reports") / f"{season}_wk{week}_reports.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    parts, ok, failed = [], 0, 0
    for gid in games["game_id"]:
        try:
            payload = build_payload(gid)
            report = breakdown.generate_breakdown(payload)
            parts.append(f"\n\n---\n\n## {gid} — {payload['mode']}-game\n\n{report}")
            ok += 1
            print(f"  [ok]   {gid}")
        except Exception as exc:  # noqa: BLE001 - keep going on a single failure
            failed += 1
            print(f"  [fail] {gid}: {exc}")

    header = f"# Film Room — {season} Week {week}\n\n*{ok} reports generated.*"
    out_path.write_text(header + "".join(parts))
    print(f"\nWrote {ok} reports ({failed} failed) -> {out_path}")
    return 0 if failed == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate Film Room report(s).")
    ap.add_argument("game_id", nargs="?",
                    help="e.g. 2025_22_SEA_NE (played) or 2026_01_NE_SEA (scheduled)")
    ap.add_argument("--season", type=int, help="batch: season (with --week)")
    ap.add_argument("--week", type=int, help="batch: generate every game this week")
    ap.add_argument("--out", help="batch: markdown output path")
    ap.add_argument("--payload-only", action="store_true",
                    help="single game: print metrics and skip the API call.")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s", datefmt="%H:%M:%S")

    if args.week is not None:
        if args.season is None:
            ap.error("--week requires --season")
        print(f"Generating {args.season} Week {args.week}…")
        return _run_week(args.season, args.week, args.out)

    if not args.game_id:
        ap.error("provide a game_id, or --season and --week for a batch")

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
