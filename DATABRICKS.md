# Deploying GridironIQ to Databricks

The warehouse is engine-portable: the **same dbt models** that run on local DuckDB
run on Databricks (Delta + Unity Catalog). Only the connection profile and the
landing step change. This is a ~15-minute, mostly-clicking setup.

```
load_delta.py                     dbt --target prod
local DuckDB raw.*  ──parquet──►  gridiron.raw.*  ──►  gridiron.marts.*   (Delta / Unity Catalog)
   (already built)                 (Delta tables)       (same models, tested)
```

## 1. Create a free Databricks workspace (one-time, you do this)

1. Sign up at **databricks.com** → *Databricks Free Edition* (verify current terms —
   free tiers change). Any cloud (AWS/Azure/GCP) works.
2. In the workspace, create a **SQL Warehouse** (SQL → SQL Warehouses → Create).
   The smallest serverless size is fine.
3. Create a **personal access token**: user avatar → *Settings → Developer →
   Access tokens → Generate new token*. Copy it — you won't see it again.

You'll need three values: the **workspace host**, the warehouse **HTTP path**
(SQL Warehouse → *Connection details*), and the **token**.

## 2. Point the tooling at it (in your shell — the token stays with you)

```bash
export DATABRICKS_HOST=adb-1234567890.11.azuredatabricks.net   # no https://
export DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/abc123def456
export DATABRICKS_TOKEN=dapiXXXXXXXXXXXXXXXX
export DATABRICKS_CATALOG=gridiron                            # optional (default: gridiron)
```

> The token lives only in your shell env. It is never written to a file, committed,
> or printed — `profiles.yml` and `load_delta.py` read it from the environment.

Install the adapter:

```bash
uv pip install --python .venv/bin/python -e ".[databricks]"
```

## 3. Land the raw tables as Delta

Builds the local DuckDB warehouse (if needed), then copies its `raw.*` tables into
`gridiron.raw.*` on Databricks via a Unity Catalog staging volume:

```bash
python warehouse/load_raw.py     # local DuckDB raw.* (skip if already built)
python warehouse/load_delta.py   # → gridiron.raw.* Delta tables
```

## 4. Build + test the marts on Databricks

```bash
cd warehouse
dbt build --profiles-dir . --target prod
```

This runs the **same** staging + mart models and the **same 31 data tests** you ran
on DuckDB — now against Delta tables in Unity Catalog. `dbt docs generate --target
prod` then serves the lineage graph.

## 5. (Optional) Point the agent + Dagster at prod

- **Scouting agent:** swap `gridiron/agent/warehouse.py`'s DuckDB connection for a
  `databricks.sql` connection (same read-only `run_sql` contract). The eval harness
  is unchanged — it re-scores the persisted run offline.
- **Dagster:** the `dbt` resource already points at the dbt project; run the job with
  `--target prod` by setting the profile target, and swap `raw_warehouse` to call
  `load_delta.py`.

## What maps to what

| Local (dev) | Databricks (prod) |
|---|---|
| `data/warehouse.duckdb` | Delta tables in Unity Catalog |
| schema `raw` / `main` | `gridiron.raw` / `gridiron.marts` |
| `load_raw.py` | `load_delta.py` |
| `profiles.yml` target `dev` | target `prod` |
| DuckDB SQL | Databricks SQL (dbt handles dialect) |

## Résumé line this unlocks

> Deployed a dbt warehouse to Databricks (Delta Lake + Unity Catalog) from a
> local DuckDB dev target with no model changes — the transformation layer is
> engine-portable, dev iterates free and fast, prod runs on the lakehouse.
