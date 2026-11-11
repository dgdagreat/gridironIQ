# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

- `.venv` is a uv-managed Python 3.11 env. There is no bare `python`; call `.venv/bin/python`.
- The `gridiron` package is **not** installed into the venv. Run everything from the repo root with `PYTHONPATH=.` (pytest works without it because it runs from the root).
- `.env` holds `ANTHROPIC_API_KEY` (see `.env.example`). Only the Film Room report and the scouting agent need it.

## Commands

```bash
# Tests (pytest, testpaths = tests/)
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest tests/test_agent_guard.py -k <expr>     # single test

# Lint — CI lints only these paths (ruff, line-length 90, py310)
.venv/bin/python -m ruff check gridiron/agent gridiron/evals orchestration \
  warehouse/load_raw.py warehouse/load_delta.py warehouse/build.py tests

# Agent eval gate — offline, rescoring the committed gridiron/evals/last_run.json
.venv/bin/python -m gridiron.evals.harness --rescore --min-pass 0.9 --min-grounded 0.9

# dbt project parses (run from warehouse/)
cd warehouse && ../.venv/bin/dbt deps --profiles-dir . && ../.venv/bin/dbt parse --profiles-dir .
```

Those four are exactly what `.github/workflows/ci.yml` runs. `ruff check .` over the
whole repo reports ~140 pre-existing errors in paths CI does not lint (`app/`, most of
`gridiron/`, `scripts/`); they are not regressions, so don't mass-fix them unasked.

The frontend has no test or lint script. `npm --prefix frontend run build` is its only check.

```bash
# React app in dev: two processes. Vite (:5173) proxies /api to the API (:8000).
PYTHONPATH=. .venv/bin/python -m uvicorn gridiron.api:app --reload --port 8000
npm --prefix frontend run dev

# Production shape: the API serves the built SPA on one origin
npm --prefix frontend run build && PYTHONPATH=. .venv/bin/python -m uvicorn gridiron.api:app --port 8000

# Streamlit app (:8501) — also the `gridironiq` config in .claude/launch.json
.venv/bin/python -m streamlit run app/streamlit_app.py

# Rebuild the data layer (network; rewrites the tracked data/gridiron.db)
PYTHONPATH=. .venv/bin/python scripts/run_cap_etl.py              # Boardroom cap tables; must run first
PYTHONPATH=. .venv/bin/python scripts/refresh_rosters.py --force  # Maxer rosters, talent, FAs, value board

# Data platform
PYTHONPATH=. .venv/bin/python warehouse/build.py                  # SQLite -> DuckDB raw.* -> dbt build + tests
.venv/bin/dagster dev -f orchestration/definitions.py             # asset graph UI
```

## Architecture

The repo is one Python package (`gridiron/`), two frontends over it, and a separate
data-platform track. `README.md` has the product and methodology detail;
`ARCHITECTURE.md` covers the platform.

### Web app: precomputed SQLite, thin API

```
ingestion (network) ──► data/gridiron.db ──► gridiron/api.py ──► frontend/ (React)
gridiron/ingestion       SQLite, tracked      FastAPI, /api/*  └► app/streamlit_app.py
```

- **Analytics are precomputed, not computed per request.** The two scripts above run
  ingestion + modeling and persist the results as SQLite tables (`positional_spending`,
  `player_talent`, `roster_strength`, `maxer_league`, `free_agents`, `value_board`, …).
  Schema and views live in `sql/`; all access goes through `gridiron/db.py`. The API
  reads those tables and only does light per-request work (team report, trade board,
  roster simulation). A modeling change is invisible in the app until the refresh
  script is rerun.
- **Film Room is the exception.** Play-by-play is downloaded from nflverse on demand
  into `data/raw/pbp_<season>.parquet` (1h TTL) and cached in memory in `api.py`, so
  the first hit for a season is slow and needs network.
- **`gridiron/api.py`** converts DataFrames with `_records(df)` (NaN → null, numpy →
  native). Anything derived only from the DB is memoized with `@_snapshot_cache()`,
  which is keyed on the DB file's mtime; the cached frames are shared across
  requests, so copy before mutating one. Successful `GET /api/*` responses are
  sent with `max-age=300` (the Vite dev proxy rewrites it to `no-store`).
  scikit-learn is imported inside the archetypes route to keep it out of cold
  start, so don't import `clustering` at module level. The block at the end of the module mounts `frontend/dist` when it exists
  and registers a catch-all SPA fallback; it must stay last so it never shadows an
  `/api/...` route. CORS only allows the Vite dev/preview origins because production
  is same-origin.
- **`frontend/`** is Vite + React 18 with no router (`App.jsx` switches sections), no
  UI or charting library (charts are hand-built SVG/CSS), and one design system in
  `src/styles.css` built on CSS variables. `src/api/client.js` is the only fetch layer.
  A new endpoint means a route in `api.py`, a method in `client.js`, and a row in the
  contract table in `frontend/README.md`.
- **Two frontends.** The React app is what Cloud Run serves. `app/streamlit_app.py` is
  the original frontend (one ~1,400-line file) and calls `gridiron` functions directly.
  Put shared logic in the `gridiron` package, and check both when changing a feature
  that exists in each.

### Shared definitions that span layers

- **Position groups.** `gridiron/ingestion/reference.py` (`POSITION_GROUPS`,
  `POSITION_GROUP_ORDER`) is the single taxonomy: QB, RB, WR, TE, T, G, C, OL, IDL,
  EDGE, LB, CB, S, SPEC. It is mirrored in `frontend/src/lib/positions.js` and pinned by
  dbt `accepted_values` tests in `warehouse/models/`, so a taxonomy change touches all three.
- **Three season constants** in `gridiron/config.py`, computed from today's date at
  import: `END_SEASON` (last finalized Super Bowl; ceiling for anything correlating
  spend with winning), `CURRENT_SEASON` (rolls over in March; pipeline and projections),
  `DEFAULT_SEASON` (rolls over in August; what the UI selects).
- **Cap share, not dollars.** Comparisons use a position's share of the cap
  (`cap_pct`, `cap_pct_norm`), and modeling defaults to 2011–2024 because the source
  data is sparse before the 2011 CBA.
- Write data files with `config.atomic_write`; overwriting in place deadlocks on a
  macOS Docker bind mount.

### Data platform track (independent of the web app)

- `warehouse/` — dbt. `load_raw.py` lands the SQLite tables into DuckDB `raw.*`
  (`data/warehouse.duckdb`, gitignored); the same models run on Databricks by switching
  the profile target (`DATABRICKS.md`).
- `lakehouse/` — PySpark + Delta medallion for play-by-play, deployed as a Databricks job.
- `orchestration/definitions.py` — one Dagster asset graph: ingestion → raw → dbt → `sb_win_model`.
- `gridiron/agent/` — `ScoutAgent`, a hand-written tool-use loop over a guarded,
  read-only `run_sql` against the DuckDB marts. It needs the warehouse built locally.
- `gridiron/evals/` — deterministic scoring of the agent on `golden_set.json`. CI
  rescores the committed traces, so no API key or warehouse is needed there.

Models: the Film Room uses `config.ANTHROPIC_MODEL`; the agent uses `GRIDIRON_SCOUT_MODEL`.

## Deploy and data flow

- **Pushing to `main` ships to production.** `.github/workflows/deploy.yml` runs Cloud
  Build (`cloudbuild.yaml` → `Dockerfile.web`) and deploys to Cloud Run. Work on a
  branch and merge by PR; CI runs on PRs to `main`.
- **`data/gridiron.db` is tracked** even though `.gitignore` has `*.db` (use
  `git add -f`). It is baked into the image. `daily-refresh.yml` regenerates it at
  13:00 UTC and commits it to `main` with `[skip ci]`, then triggers a deploy. Local
  `main` therefore goes stale daily: pull before branching, and don't commit a locally
  regenerated DB unless that is the point of the change.
- The root `Dockerfile` is the Dagster/platform image; `Dockerfile.web` is the deployed web app.
- `WHERE_WE_LEFT_OFF.md` is a session handoff note and parts of it are out of date.
  It describes a Streamlit Cloud deployment of the Streamlit app that also redeploys
  from `main`, can lag a commit, and needs a manual reboot to pick up new code.
