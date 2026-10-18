"""Land raw GridironIQ tables into the DuckDB warehouse (`raw` schema).

This is the ingestion -> warehouse boundary. The Python `gridiron` package
already produces clean, deduped tables in SQLite (data/gridiron.db) and raw
parquet in data/raw/; this step copies them, unchanged, into a columnar DuckDB
warehouse that dbt then transforms. On Databricks the equivalent step writes
these same tables as Delta tables in Unity Catalog -- dbt sits on top either way.

Idempotent: drops and recreates the `raw` schema every run.

Usage:
    python warehouse/load_raw.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[1]
SQLITE_DB = REPO / "data" / "gridiron.db"
WAREHOUSE = REPO / "data" / "warehouse.duckdb"
RAW_DIR = REPO / "data" / "raw"

# Raw parquet files worth landing alongside the Boardroom tables. dbt can lean
# on these later (e.g. roster/Madden joins) without re-reading files ad hoc.
PARQUET_SOURCES = {
    "roster_2026": RAW_DIR / "roster_2026.parquet",
    "roster_2025": RAW_DIR / "roster_2025.parquet",
    "madden_2025": RAW_DIR / "madden_2025.parquet",
    "historical_contracts": RAW_DIR / "historical_contracts.parquet",
    "snap_counts_2024": RAW_DIR / "snap_counts_2024.parquet",
}


def main() -> int:
    if not SQLITE_DB.exists():
        print(f"ERROR: {SQLITE_DB} not found -- run the Boardroom ETL first.")
        return 1

    con = duckdb.connect(str(WAREHOUSE))
    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute("DROP SCHEMA IF EXISTS raw CASCADE;")
    con.execute("CREATE SCHEMA raw;")

    # ---- SQLite Boardroom tables -> raw.* -------------------------------
    con.execute(f"ATTACH '{SQLITE_DB}' AS boardroom (TYPE sqlite);")
    tables = [
        r[0]
        for r in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_catalog='boardroom' AND table_type='BASE TABLE' "
            "ORDER BY table_name"
        ).fetchall()
    ]
    for t in tables:
        con.execute(f'CREATE TABLE raw."{t}" AS SELECT * FROM boardroom."{t}";')
    con.execute("DETACH boardroom;")
    print(f"landed {len(tables)} SQLite tables: {', '.join(tables)}")

    # ---- raw parquet -> raw.* -------------------------------------------
    landed_pq = []
    for name, path in PARQUET_SOURCES.items():
        if not path.exists():
            print(f"  skip {name}: {path} missing")
            continue
        con.execute(
            f'CREATE OR REPLACE TABLE raw."{name}" AS '
            f"SELECT * FROM read_parquet(?);",
            [str(path)],
        )
        landed_pq.append(name)
    print(f"landed {len(landed_pq)} parquet sources: {', '.join(landed_pq)}")

    total = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema='raw'"
    ).fetchone()[0]
    con.close()
    print(f"OK -> {WAREHOUSE} ({total} tables in schema `raw`)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
