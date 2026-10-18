# GridironIQ Warehouse (dbt)

The analytical warehouse layer. The Python `gridiron` package owns **ingestion**
(the OverTheCap / nflverse / Madden traps it already solves); **dbt owns every
transformation downstream**, as tested, documented, version-controlled SQL.

```
gridiron (Python)          load_raw.py            dbt
ingestion  ───────────►  raw.* tables  ───────►  staging ──► marts
(SQLite + parquet)       (DuckDB / Delta)        (views)     (tables)
```

## Dev vs. prod — the same models, two engines

| Target | Engine | Cost | Use |
|--------|--------|------|-----|
| `dev`  | **DuckDB** (`data/warehouse.duckdb`) | free, local | iterate fast |
| `prod` | **Databricks** (Delta + Unity Catalog) | free tier | the résumé build |

Because everything is dbt, the transformation code is identical across engines —
only `profiles.yml` changes. Develop locally, deploy to the cloud warehouse.

## Run it

```bash
# 1. Land raw tables into the DuckDB warehouse (ingestion -> warehouse boundary)
python warehouse/load_raw.py

# 2. Build + test all models  (run from this directory)
cd warehouse
dbt deps  --profiles-dir .      # first time only (installs dbt_utils)
dbt build --profiles-dir .      # runs models AND data tests
dbt docs generate --profiles-dir . && dbt docs serve --profiles-dir .   # lineage graph
```

Or the whole thing in one shot from the repo root:

```bash
python warehouse/build.py
```

## Models

**staging/** (views — typed, renamed, keyed 1:1 off raw)
- `stg_positional_spending`, `stg_spending_features`, `stg_team_outcomes`, `stg_league_cap`

**marts/** (tables — the analytical layer, rebuilds the old SQLite `v_*` views)
- `dim_season` — season / league cap / era / finalized-vs-projection flag
- `fct_team_season` — one row per team-season: positional cap-share features + SB target
- `int_positional_long` — long positional spending tagged with SB outcomes
- `mart_position_success` — **the headline**: champion cap premium by position
- `mart_positional_era_avg` — era-aware positional baselines

## Data quality (31 tests)

`unique` / `not_null` on every grain key, `accepted_values` on `pos_group` and the
binary SB flags, `relationships` (team-season → `dim_season`), and a
`dbt_utils.accepted_range` asserting `cap_pct` is a valid 0–1 fraction. A red test
fails the build — this is where the old ad-hoc `crosscheck_rosters.py` logic becomes
enforced, in-pipeline data contracts.

## Deploying to Databricks

The `prod` target (Databricks / Delta / Unity Catalog) is already wired in
`profiles.yml`, and `load_delta.py` lands raw as Delta. Full runbook:
[../DATABRICKS.md](../DATABRICKS.md). In short:

```bash
pip install -e ".[databricks]"
export DATABRICKS_HOST=... DATABRICKS_HTTP_PATH=... DATABRICKS_TOKEN=...
python warehouse/load_delta.py                       # raw.* → Delta
dbt build --profiles-dir . --target prod             # same models + tests, on the lakehouse
```
