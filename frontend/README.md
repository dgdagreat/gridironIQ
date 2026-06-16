# GridironIQ — React frontend (planned)

The **working** frontend today is the Streamlit app at [`app/streamlit_app.py`](../app/streamlit_app.py)
(`streamlit run app/streamlit_app.py`) — it already delivers the two required
tabs (Boardroom, Film Room) against the live SQLite model. Per the project brief,
Streamlit is the pragmatic alternative; this folder is reserved for the React
build, scaffolded here so the next phase has a clear contract.

## Planned structure (Vite + React)

```
frontend/
├── index.html
├── package.json
├── vite.config.js
└── src/
    ├── main.jsx
    ├── App.jsx                 # tab shell: <Boardroom/> | <FilmRoom/>
    ├── api/client.js           # fetch wrapper around the JSON API below
    ├── components/
    │   ├── Tabs.jsx
    │   ├── ChampionPremiumChart.jsx
    │   ├── TeamSpendingExplorer.jsx
    │   ├── ArchetypeTable.jsx
    │   └── FilmBreakdown.jsx
    └── tabs/
        ├── Boardroom.jsx
        └── FilmRoom.jsx
```

## API contract (to be served by a small FastAPI layer over `gridiron`)

A thin `gridiron/api.py` (FastAPI) would expose the already-built analytics:

| Method | Route                              | Backed by |
|--------|------------------------------------|-----------|
| GET    | `/api/champion-premium`            | `cap_efficiency.champion_premium()` |
| GET    | `/api/efficiency-verdict`          | `cap_efficiency.efficiency_verdict()` |
| GET    | `/api/team-season/{team}/{season}` | `positional_spending` table |
| GET    | `/api/archetypes?k=5`              | `clustering.cluster_archetypes()` |
| POST   | `/api/film/breakdown`              | `pbp_metrics` + `breakdown.generate_breakdown()` |

The analytics functions already return tidy DataFrames, so each route is a
`.to_dict(orient="records")` away. Build order: FastAPI layer → `api/client.js`
→ port each Streamlit panel to its React component.
```
```
