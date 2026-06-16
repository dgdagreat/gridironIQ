#!/usr/bin/env python3
"""CLI entry point for the Boardroom cap ETL.

Usage:
    python scripts/run_cap_etl.py            # incremental (uses cached download)
    python scripts/run_cap_etl.py --force-download
    python scripts/run_cap_etl.py -v         # debug logging
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow running as a plain script (no install required).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gridiron.ingestion.load_cap import run_etl  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the GridironIQ cap ETL.")
    parser.add_argument("--force-download", action="store_true",
                        help="Re-download the contracts source even if cached.")
    parser.add_argument("--no-processed", action="store_true",
                        help="Skip writing processed CSV/parquet extracts.")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable debug-level logging.")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    summary = run_etl(
        force_download=args.force_download,
        save_processed=not args.no_processed,
    )

    print("\n" + "=" * 52)
    print(" GridironIQ cap ETL -- summary")
    print("=" * 52)
    for key, value in summary.items():
        print(f"  {key:<18} {value}")
    print("=" * 52)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
