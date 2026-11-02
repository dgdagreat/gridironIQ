# GridironIQ — React frontend

A Vite + React frontend over the `gridiron` analytics, talking to a thin FastAPI
JSON layer (`gridiron/api.py`). The Streamlit app (`app/streamlit_app.py`) is
still the canonical, feature-complete frontend; this is the in-progress React
port, kicked off with the Boardroom and Film Room tabs.

## Run it (two processes)

**1. The API** (from the repo root):

```bash
PYTHONPATH=. .venv/bin/python -m uvicorn gridiron.api:app --reload --port 8000
```

**2. The dev server** (from `frontend/`):

```bash
npm install
npm run dev
```

Open http://localhost:5173 — Vite proxies `/api/*` to the API on :8000, so
there's no CORS setup in dev. Point at a different API with
`GRIDIRON_API_URL=… npm run dev`.

The Film Room's "Write the film report" button calls Anthropic, so the API
process needs `ANTHROPIC_API_KEY` in its environment; everything else works
without a key.

## Structure

```
frontend/
├── index.html
├── vite.config.js            # react plugin + /api dev proxy
└── src/
    ├── main.jsx
    ├── App.jsx               # tab shell: <Boardroom/> | <FilmRoom/>
    ├── styles.css            # dark analytics theme (CSS variables)
    ├── api/client.js         # fetch wrapper around the JSON API
    ├── lib/useAsync.js       # loading/error/data hook
    ├── components/
    │   ├── Async.jsx                 # loading/error/empty wrapper
    │   ├── ChampionPremiumChart.jsx  # recharts diverging bar
    │   ├── EfficiencyVerdictTable.jsx
    │   ├── TeamSpendingExplorer.jsx
    │   └── ArchetypeTable.jsx
    └── tabs/
        ├── Boardroom.jsx
        └── FilmRoom.jsx
```

## API contract (served by `gridiron/api.py`)

| Method | Route                              | Backed by |
|--------|------------------------------------|-----------|
| GET    | `/api/meta`                        | seasons / teams / current season (dropdowns) |
| GET    | `/api/champion-premium`            | `cap_efficiency.champion_premium()` |
| GET    | `/api/efficiency-verdict`          | `cap_efficiency.efficiency_verdict()` |
| GET    | `/api/team-season/{team}/{season}` | `positional_spending` + `player_year_caps` |
| GET    | `/api/archetypes?k=5`              | `clustering.cluster_archetypes()` |
| GET    | `/api/maxer/{team}`                | roster outlook, needs, free agents, trades |
| GET    | `/api/value-board?position=&limit=` | best values and overpays |
| GET    | `/api/film/games?season=`          | `schedules.list_games()` |
| GET    | `/api/film/summary?season=&game_id=` | `pbp_metrics.build_breakdown_payload()` (no LLM) |
| POST   | `/api/film/breakdown`              | `breakdown.generate_breakdown()` (Anthropic) |

## Port status

The React shell now includes all four Streamlit tabs. The Maxer includes team
outlook, position gaps, recommended free agents and trade targets, plus an
interactive roster simulator and projected starters view. The Value Board
includes best values and overpays. The Boardroom's cap gauge / spending donut /
SB-blueprint radar overlay remain to be ported.
