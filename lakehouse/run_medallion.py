"""Driver — build the nflfastR PBP medallion: Bronze -> Silver -> Gold.

Ingestion stays in the `gridiron` package (it already owns the nflverse download +
cache); this driver lands the raw parquet through it, then Spark does the heavy
transformation. The same script is the entry point for the Databricks Job.

    # local (delta-spark)
    python -m lakehouse.run_medallion --start 2015 --end 2025
    python -m lakehouse.run_medallion --skip-ingest --layers silver,gold

    # Databricks: a spark_python_task pointing at this file (see databricks.yml)
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Make `lakehouse` and `gridiron` importable whether run as a module or a file.
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from lakehouse import bronze, gold, paths, silver          # noqa: E402
from lakehouse.spark_session import get_spark              # noqa: E402


def ensure_raw(seasons, force: bool = False) -> None:
    """Land raw nflfastR PBP via gridiron ingestion (gridiron owns ingestion)."""
    try:
        from gridiron.filmroom import pbp_metrics
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] gridiron ingestion unavailable ({exc}); "
              f"expecting raw files already in {paths.RAW_PBP_DIR}")
        return
    for s in seasons:
        try:
            pbp_metrics.load_pbp(s, force=force)
        except Exception as exc:  # noqa: BLE001 - a missing season shouldn't kill the run
            print(f"[warn] could not land raw PBP for {s}: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Build the nflfastR PBP medallion (Bronze/Silver/Gold).")
    ap.add_argument("--start", type=int, default=paths.SEASON_MIN)
    ap.add_argument("--end", type=int, default=paths.SEASON_MAX)
    ap.add_argument("--layers", default="bronze,silver,gold",
                    help="comma list of layers to build")
    ap.add_argument("--skip-ingest", action="store_true",
                    help="assume raw PBP parquet is already present")
    ap.add_argument("--force", action="store_true", help="re-download raw PBP")
    args = ap.parse_args()

    seasons = range(args.start, args.end + 1)
    layers = {x.strip() for x in args.layers.split(",") if x.strip()}

    if not args.skip_ingest:
        print(f"landing raw PBP {args.start}-{args.end} via gridiron ...")
        ensure_raw(seasons, force=args.force)

    spark = get_spark()
    t0 = time.time()
    if "bronze" in layers:
        b = bronze.build_bronze(spark, seasons)
        print(f"bronze/pbp:        {b.count():>9,} rows")
    if "silver" in layers:
        s = silver.build_silver(spark)
        print(f"silver/plays:      {s.count():>9,} rows")
    if "gold" in layers:
        tg, ts = gold.build_gold(spark)
        print(f"gold/team_game:    {tg.count():>9,} rows")
        print(f"gold/team_season:  {ts.count():>9,} rows")
    print(f"done in {time.time() - t0:.1f}s  ->  {paths.LAKE_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
