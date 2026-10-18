"""Land raw GridironIQ tables into Databricks as Delta tables (the prod analog of
load_raw.py). dbt then transforms them identically to the DuckDB dev flow.

Approach (no Spark cluster required — just a SQL warehouse):
  1. Export each local DuckDB `raw.*` table to a parquet file.
  2. PUT it into a Unity Catalog staging volume.
  3. CREATE OR REPLACE the Delta table from it via read_files() (types preserved).

Credentials come from the environment — the token is never written or logged:
    export DATABRICKS_HOST=adb-xxxx.azuredatabricks.net   # no https://
    export DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/xxxx
    export DATABRICKS_TOKEN=dapi...
    export DATABRICKS_CATALOG=gridiron                    # optional, default 'gridiron'

    python warehouse/load_delta.py

NOTE: requires a live Databricks workspace + SQL warehouse. Not exercised in the
DuckDB dev flow. `dbt build --profiles-dir . --target prod` runs after this.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[1]
LOCAL_WAREHOUSE = REPO / "data" / "warehouse.duckdb"

# The tables dbt declares as sources (warehouse/models/staging/_sources.yml).
SOURCE_TABLES = [
    "positional_spending",
    "spending_features",
    "team_outcomes",
    "league_cap",
    "super_bowls",
    "player_year_caps",
    "roster_strength",
    "value_board",
]


def _env(name: str, default: str | None = None) -> str:
    val = os.getenv(name, default)
    if not val:
        sys.exit(f"ERROR: environment variable {name} is not set (see this file's docstring).")
    return val


def main() -> int:
    host = _env("DATABRICKS_HOST")
    http_path = _env("DATABRICKS_HTTP_PATH")
    token = _env("DATABRICKS_TOKEN")
    catalog = os.getenv("DATABRICKS_CATALOG", "gridiron")
    schema = "raw"
    volume = "_staging"

    try:
        from databricks import sql as dbsql
    except ImportError:
        sys.exit("ERROR: pip install -e '.[databricks]' first (dbt-databricks pulls the connector).")

    if not LOCAL_WAREHOUSE.exists():
        sys.exit(f"ERROR: {LOCAL_WAREHOUSE} not found — run `python warehouse/load_raw.py` first.")

    duck = duckdb.connect(str(LOCAL_WAREHOUSE), read_only=True)
    tmp = Path(tempfile.mkdtemp(prefix="gridiron_delta_"))

    con = dbsql.connect(
        server_hostname=host,
        http_path=http_path,
        access_token=token,
        staging_allowed_local_path=str(tmp),  # required for PUT
    )
    cur = con.cursor()
    vol_root = f"/Volumes/{catalog}/{schema}/{volume}"
    cur.execute(f"CREATE CATALOG IF NOT EXISTS {catalog}")
    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")
    cur.execute(f"CREATE VOLUME IF NOT EXISTS {catalog}.{schema}.{volume}")

    for t in SOURCE_TABLES:
        local_pq = tmp / f"{t}.parquet"
        duck.execute(f"COPY (SELECT * FROM raw.\"{t}\") TO '{local_pq}' (FORMAT parquet)")
        cur.execute(f"PUT '{local_pq}' INTO '{vol_root}/{t}.parquet' OVERWRITE")
        cur.execute(
            f"CREATE OR REPLACE TABLE {catalog}.{schema}.{t} AS "
            f"SELECT * FROM read_files('{vol_root}/{t}.parquet', format => 'parquet')"
        )
        n = cur.execute(f"SELECT count(*) FROM {catalog}.{schema}.{t}").fetchone()[0]
        print(f"  {catalog}.{schema}.{t:22s} <- {n} rows")

    cur.close()
    con.close()
    duck.close()
    print(f"OK -> landed {len(SOURCE_TABLES)} Delta tables in {catalog}.{schema}")
    print("Next: cd warehouse && dbt build --profiles-dir . --target prod")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
