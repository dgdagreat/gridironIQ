# GridironIQ Orchestration (Dagster)

One asset graph for the whole platform — Python ingestion, the dbt warehouse, and
the ML model — with lineage, retries, and a daily schedule. Replaces the launchd
`com.gridironiq.refresh` cron.

## The graph

```
boardroom_cap_etl ┐
                  ├─► raw/<8 tables> ─► stg_* ─┬─► int_positional_long ─► mart_position_success
maxer_rosters ────┘   (load_raw.py)   (dbt)    │                        └─► mart_positional_era_avg
                                               ├─► dim_season
                                               └─► fct_team_season ─► sb_win_model (CV AUC)
```

- **ingestion** — `boardroom_cap_etl`, `maxer_rosters` wrap the existing scripts
  (they still own every OverTheCap / nflverse trap).
- **warehouse** — `raw_warehouse` multi-asset runs `load_raw.py`, emitting one
  asset per raw table keyed `["raw", <table>]` to match the dbt sources.
- **dbt** — every staging + mart model is a Dagster asset via `dagster-dbt`, so
  `dbt build` runs inside the graph with per-model lineage and test results.
- **modeling** — `sb_win_model` trains on the dbt `fct_team_season` and logs
  5-fold CV AUC as asset metadata.

## Run it

```bash
# Launch the Dagster UI (asset graph, run history, schedule, logs)
dagster dev -f orchestration/definitions.py
```

```bash
# Headless: materialize everything downstream of ingestion (offline, no network)
dagster asset materialize -f orchestration/definitions.py \
  --select "group:warehouse,group:default,group:modeling"
```

```bash
# Full refresh incl. network ingestion (what the 6am schedule runs)
dagster asset materialize -f orchestration/definitions.py --select "*"
```

Set `DAGSTER_HOME` to persist run history across sessions:
`export DAGSTER_HOME="$PWD/.dagster_home"`.

## Schedule

`daily_refresh_6am` (cron `0 6 * * *`) materializes all assets — the Dagster-native
replacement for the launchd plist. Turn it on from the UI's **Automation** tab, or
run `dagster-daemon run` alongside the webserver.

## Deploying to Databricks

The graph is engine-agnostic: point the `dbt` resource's profile at the Databricks
`prod` target (see `warehouse/README.md`) and the same dbt assets run on Delta /
Unity Catalog. Ingestion + `load_raw` write Delta instead of SQLite/DuckDB.
