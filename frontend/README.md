# GridironIQ — React frontend

The Vite + React app that Cloud Run serves. It talks to a thin FastAPI JSON layer
(`gridiron/api.py`) and covers all four areas: the cap-efficiency **Boardroom**,
the **Film Room**, the **Super Bowl Maxer** (field diagram and roster simulator),
and the **Value Board**. The Streamlit app (`app/streamlit_app.py`) is the
original frontend and calls the `gridiron` package directly, so a feature that
exists in both needs checking in both.

## Run it

**Development (two processes).** Start the API from the repo root:

```bash
PYTHONPATH=. .venv/bin/python -m uvicorn gridiron.api:app --reload --port 8000
```

Then the dev server from `frontend/`:

```bash
npm install && npm run dev
```

Open http://localhost:5173. Vite proxies `/api/*` to the API on `:8000`, so there
is no CORS setup in development.

**Production shape (one origin).** `npm run build` writes `frontend/dist`, and the
API serves it when that folder exists. Run the build, start the API without
`--reload`, and open http://localhost:8000.

**Environment**

| Variable | Read by | Purpose |
|---|---|---|
| `GRIDIRON_API_URL` | `vite.config.js` | Dev proxy target. Defaults to `http://localhost:8000`. |
| `VITE_API_BASE` | `src/api/client.js` | Prefix for every request. Defaults to empty (same origin). |
| `ANTHROPIC_API_KEY` | the API process | Only for the Film Room's "Generate film report" button. Everything else works without it. |

**Checks.** There is no test or lint script. `npm run build` is the only check.

## Structure

```
frontend/
├── index.html                 # Google Fonts (Space Grotesk, Inter)
├── vite.config.js             # React plugin + /api dev proxy
└── src/
    ├── main.jsx
    ├── App.jsx                # masthead + section switch (no router)
    ├── styles.css             # the design system (CSS variables, no UI dependencies)
    ├── api/client.js          # the only fetch layer
    ├── lib/
    │   ├── useAsync.js        # run a loader, expose {data, loading, error}
    │   ├── format.js          # pct, signedPct, usd, num
    │   └── positions.js       # position names, unit split, radar spoke order
    ├── components/
    │   ├── Async.jsx          # loading / error / empty states
    │   ├── Field.jsx          # labelled <select>
    │   ├── PosTag.jsx         # position color tag
    │   ├── PremiumChart.jsx   # diverging bars: champion premium by position
    │   ├── VerdictTable.jsx   # per-position efficiency verdict
    │   ├── TeamExplorer.jsx   # one team-season deep dive, built from the five below
    │   ├── CapGauge.jsx       #   committed cap against the league cap
    │   ├── SpendingDonut.jsx  #   offense / defense / special teams split
    │   ├── BlueprintRadar.jsx #   team spending shape over the champion average
    │   ├── BlueprintGap.jsx   #   per-position gap to the champion average
    │   ├── EpaPanel.jsx       #   on-field EPA for the season
    │   ├── TeamCompare.jsx    # up to six teams, cap share by position
    │   └── Archetypes.jsx     # k-means roster archetypes
    └── sections/
        ├── Boardroom.jsx
        ├── FilmRoom.jsx       # game picker, summary, quarter subtotals, play log, report
        ├── Maxer.jsx          # outlook tiles, field diagram, roster simulator
        └── ValueBoard.jsx     # best values and biggest overpays
```

## Conventions

- **No router.** `App.jsx` holds the active section in state and switches views.
- **No UI or charting library.** Every chart is hand-built SVG or CSS, which keeps
  dependencies to React and Vite.
- **One fetch layer.** Components call `api.*` from `src/api/client.js` through
  `useAsync`. A failed request throws an `Error` carrying the API's `detail`
  message and the HTTP `status`.
- **Adding an endpoint** means a route in `gridiron/api.py`, a method in
  `client.js`, and a row in the table below.
- **Position groups** in `src/lib/positions.js` mirror
  `gridiron/ingestion/reference.py`. A taxonomy change touches both, plus the dbt
  tests in `warehouse/models/`.

## API contract (served by `gridiron/api.py`)

| Method | Route | Client method | Returns |
|--------|-------|---------------|---------|
| GET  | `/api/health` | — | liveness check |
| GET  | `/api/meta` | `meta` | seasons, teams, current and projection season, divisions |
| GET  | `/api/champion-premium` | `championPremium` | `cap_efficiency.champion_premium()` |
| GET  | `/api/efficiency-verdict` | `efficiencyVerdict` | `cap_efficiency.efficiency_verdict()` |
| GET  | `/api/team-season/{team}/{season}` | `teamSeason` | `positional_spending` + `player_year_caps`, plus season EPA and rank when the lakehouse covers that season |
| GET  | `/api/compare?season=&teams=` | `compare` | normalized cap share by position for up to six comma-separated teams |
| GET  | `/api/archetypes?k=` | `archetypes` | `clustering.cluster_archetypes()`, with `k` from 2 to 10 |
| GET  | `/api/maxer/{team}` | `maxer` | `sb_maxer` + `trade_market`: report, needs, free agents, trade targets, league table, starters |
| POST | `/api/maxer/{team}/simulate` | `maxerSimulate` | body `{signed, traded}`, at most 12 moves: recomputed report, league table, starters, and readiness deltas |
| GET  | `/api/value-board?position=&limit=` | `valueBoard` | `value_board`: best values and biggest overpays |
| GET  | `/api/film/games?season=` | `filmGames` | `schedules.list_games()` |
| GET  | `/api/film/summary?season=&game_id=` | `filmSummary` | `pbp_metrics.build_breakdown_payload()` (no LLM call) |
| GET  | `/api/film/subtotals?season=&game_id=` | `filmSubtotals` | per-offense plays, yards, EPA, EPA/play, and success rate, by quarter and for the game |
| GET  | `/api/film/plays?season=&game_id=` | `filmPlays` | every snap with down, distance, play type, yards, EPA, and description, grouped by quarter |
| POST | `/api/film/breakdown` | `filmBreakdown` | body `{season, game_id}`: `breakdown.generate_breakdown()` (Anthropic); 503 when the key is missing |

Every Film Room route except `/api/film/games` loads play-by-play for the season
on first use, so the first request is slow and needs network access. It is
cached in memory for an hour.
