# GridironIQ — React frontend

A Vite + React frontend over the `gridiron` analytics, talking to a thin FastAPI
JSON layer (`gridiron/api.py`). The Streamlit app (`app/streamlit_app.py`) remains
the canonical frontend; this is a designed web experience covering all four areas:
the cap-efficiency **Boardroom**, the **Film Room**, the **Super Bowl Maxer**
(field diagram + roster simulator), and the **Value Board**.

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

Open http://localhost:5173 — Vite proxies `/api/*` to the API on :8000, so there's
no CORS setup in dev. Point at a different API with `GRIDIRON_API_URL=… npm run dev`.

The Film Room's "Generate film report" button calls Anthropic, so the API process
needs `ANTHROPIC_API_KEY` in its environment; everything else works without a key.

## Structure

```
frontend/
├── index.html                # Google Fonts (Space Grotesk / Inter)
├── vite.config.js            # react plugin + /api dev proxy
└── src/
    ├── main.jsx
    ├── App.jsx               # masthead + section switch
    ├── styles.css            # the design system (CSS variables, no UI deps)
    ├── api/client.js         # fetch wrapper around the JSON API
    ├── lib/{useAsync,format}.js
    ├── components/           # Async, Field, PremiumChart, VerdictTable,
    │                         # TeamExplorer, Archetypes
    └── sections/
        ├── Boardroom.jsx
        ├── FilmRoom.jsx
        ├── Maxer.jsx         # outlook tiles, field diagram, roster simulator
        └── ValueBoard.jsx
```

## API contract (served by `gridiron/api.py`)

| Method | Route | Backed by |
|--------|-------|-----------|
| GET  | `/api/meta` | seasons / teams / current season |
| GET  | `/api/champion-premium` | `cap_efficiency.champion_premium()` |
| GET  | `/api/efficiency-verdict` | `cap_efficiency.efficiency_verdict()` |
| GET  | `/api/team-season/{team}/{season}` | `positional_spending` + `player_year_caps` |
| GET  | `/api/archetypes?k=` | `clustering.cluster_archetypes()` |
| GET  | `/api/maxer/{team}` | `sb_maxer` + `trade_market` — outlook, needs, FAs, trades, starters |
| POST | `/api/maxer/{team}/simulate` | recompute after selected signings / trades |
| GET  | `/api/value-board?position=&limit=` | `value_board` — best values and overpays |
| GET  | `/api/film/games?season=` | `schedules.list_games()` |
| GET  | `/api/film/summary?season=&game_id=` | `pbp_metrics.build_breakdown_payload()` (no LLM) |
| POST | `/api/film/breakdown` | `breakdown.generate_breakdown()` (Anthropic) |

No charting library is used anywhere — the premium diverging bars and the Maxer
field diagram are hand-built in CSS/SVG, keeping deps to just React + Vite.
