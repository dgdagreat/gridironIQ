# Backend Position Changes — Review Notes

## Issue

The backend grouped every offensive lineman into a single `OL` bucket. That hid
differences between offensive tackles, guards, and centers in cap spending,
roster strength, and team needs. The role labels were also not represented as
separate spending features in the warehouse or clearly named in reports.

## Changes made

- Position normalization now maps tackle labels (`T`, `OT`, `LT`, `RT`, and full
  tackle names) to `T`; guard labels (`G`, `OG`, `LG`, `RG`, and full guard
  names) to `G`; and center labels (`C` and center name variants) to `C`.
- Generic source labels (`OL`, `IOL`) remain in `OL` when the source does not
  provide enough information to assign a specific role.
- Cap spending and model feature generation can now retain separate `T`, `G`,
  and `C` values. The SQL schema and warehouse staging model include the new
  feature columns.
- Roster strength uses distinct T/G/C units and keeps a generic OL fallback.
  The Maxer lineup assigns its five offensive line slots to the appropriate
  role groups, and trade estimates recognize the new groups.
- Streamlit, React, and Tableau labels display “Offensive Tackle,” “Offensive
  Guard,” and “Center.”

## Files changed

- `gridiron/ingestion/reference.py`
- `gridiron/modeling/roster_strength.py`
- `gridiron/modeling/trade_market.py`
- `gridiron/api.py`
- `app/streamlit_app.py`
- `sql/01_schema.sql`
- `warehouse/models/staging/stg_spending_features.sql`
- `warehouse/models/staging/_staging.yml`
- `warehouse/models/marts/_marts.yml`
- `tableau/export_data.py`
- `frontend/src/components/ChampionPremiumChart.jsx`
- `frontend/src/components/EfficiencyVerdictTable.jsx`

## Review points

1. Confirm the source position labels cover the formats present in the cap and
   roster feeds. Unknown or generic OL labels intentionally cannot be split.
2. Rebuild the ingested tables and downstream warehouse/Tableau exports before
   reviewing results. Existing stored data still has the old aggregated OL
   values until refreshed.
3. Check downstream consumers that expect the old `pct_OL` feature or only the
   original position list. The new feature columns are `pct_T`, `pct_G`, and
   `pct_C`; `pct_OL` now represents generic labels only.
4. Interpret historical OL comparisons with care: granular source labels will
   now be allocated to T/G/C, so the old combined OL trend is no longer directly
   represented by the OL row alone.
5. Automated tests were not run for this change. `git diff --check` passed.

## Backend audit findings

Static review only; no tests or live data pipelines were run. The findings below
have been addressed in code.

### High priority — fixed

- **Read-only SQL can still read outside the warehouse.**
  [`gridiron/agent/warehouse.py:81`](/Users/daejuangraham/dev/gridironIQ/gridiron/agent/warehouse.py:81)
  checks that SQL starts with `SELECT`/`WITH` and blocks a keyword list, but it
  does not constrain referenced schemas or table functions. A query can use
  DuckDB readers such as `read_csv`/`read_parquet` to attempt reading local files
  through the agent. The read-only connection prevents database writes, but it
  is not a filesystem read boundary. The agent connection now also disables
  DuckDB external access, locks those settings, and sets memory, thread, and
  execution-time limits for submitted queries.
- **Cap ETL drops the live tables before loading replacements.**
  [`gridiron/ingestion/load_cap.py:58`](/Users/daejuangraham/dev/gridironIQ/gridiron/ingestion/load_cap.py:58)
  runs the schema script, which drops/recreates the tables, then writes each
  output table in separate operations. A failure mid-load could leave empty or
  partial data. Table and view replacement now runs in one SQLite transaction,
  restoring the last complete dataset if the refresh fails.

### Medium priority — fixed

- **Live schedule cache does not expire in a running process.**
  [`gridiron/ingestion/schedules.py:29`](/Users/daejuangraham/dev/gridironIQ/gridiron/ingestion/schedules.py:29)
  previously memoized `load_schedules` outside its TTL check. It now uses an
  expiring in-memory cache and returns copies. Current-season PBP now refreshes
  from disk/network on a one-hour TTL, including the API's in-memory cache.
- **Spark pressure rate can count a sack twice.**
  [`lakehouse/gold.py:39`](/Users/daejuangraham/dev/gridironIQ/lakehouse/gold.py:39)
  adds `qb_hit` and `sack` totals. A sack can also have `qb_hit=1`, causing the
  numerator to exceed actual dropbacks and pressure rate to exceed 100%. Spark
  now counts each pressured dropback once, and Film Room form metrics use
  `qb_dropback` when present.
- **Lakehouse play selection and explosive rate differ from the app metrics.**
  [`lakehouse/silver.py:33`](/Users/daejuangraham/dev/gridironIQ/lakehouse/silver.py:33)
  retains kneels, spikes, and null play types, while its explosive-play formula
  treated every non-pass as a rush. Silver now filters to run/pass plays and
  classifies explosive plays from their play type, matching the app denominator.
- **Value-board position filter only applies to the best list.**
  [`gridiron/api.py:307`](/Users/daejuangraham/dev/gridironIQ/gridiron/api.py:307)
  filtered `best` by the requested position, but returned `worst_contracts` for
  all positions. The requested position now filters both lists.
- **Scout prompt still documents the old position taxonomy.**
  [`gridiron/agent/scout.py:33`](/Users/daejuangraham/dev/gridironIQ/gridiron/agent/scout.py:33)
  omitted `T`, `G`, and `C` from `SEMANTIC_NOTES`. The prompt now lists the new
  groups and explains that `OL` means a generic source label.
- **Roster model cross-validation can leak the same player's season across folds.**
  [`gridiron/modeling/player_value.py:134`](/Users/daejuangraham/dev/gridironIQ/gridiron/modeling/player_value.py:134)
  and [`gridiron/modeling/defense_value.py:129`](/Users/daejuangraham/dev/gridironIQ/gridiron/modeling/defense_value.py:129)
  built multiple cutoff rows for each player and then used row-level random
  folds. Both models now use grouped folds so one player's snapshots stay in a
  single fold.
- **Simulation accepts unvalidated trade IDs.**
  [`gridiron/api.py:254`](/Users/daejuangraham/dev/gridironIQ/gridiron/api.py:254)
  silently ignored unknown IDs and permitted moving a team's own player to
  itself. Requests now have a validated schema, reject unknown teams, and accept
  trade IDs only when they appear on that team's current trade board.

### Operational behavior updated

The API reloads database tables and metadata per request. Schedule data has a
bounded TTL, and organization scoring now derives its weights from the latest
season with a completed Super Bowl rather than a hard-coded year list.

