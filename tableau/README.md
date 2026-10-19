# GridironIQ — Tableau dashboard

The visualization layer on top of the GridironIQ pipeline. The dbt marts answer
*"how do Super Bowl teams build a roster under the cap?"*; this turns that into a
public, interactive Tableau Public dashboard — the kind of single link you drop
on a résumé or LinkedIn.

## The story the dashboard tells

**NFL Roster Construction: what championship teams pay for.** Across ~25 years of
cap data, champions systematically *overspend* at a few positions and get *value*
at others — and on-field EPA shows which teams are actually efficient today.

## Data

`export_data.py` reads the local DuckDB warehouse (the dbt marts) and writes these
tidy CSVs to `data/`. Regenerate any time with:

```bash
.venv/bin/python tableau/export_data.py
```

| File | Grain | Use for |
|---|---|---|
| `champion_premium_by_position.csv` | 1 row / position (11) | **Headline:** diverging bar — pay-up vs value positions (`champion_premium`) |
| `positional_spending_by_era.csv` | position × era (44) | Heatmap/line — how cap allocation shifted across eras (`avg_cap_pct`) |
| `team_season_positional_long.csv` | team-season-position (11,990) | Spend-vs-outcome analysis, filter by `outcome` (Won SB / appeared / neither) |
| `team_epa.csv` | 1 row / team (32) | On-field efficiency leaderboard (`net_epa_play`, off/def split) |
| `value_board.csv` | 1 row / player (660) | Scatter — caliber vs pay, bubbles sized by `value_index` |

### Key fields
- `champion_premium` — champion avg cap share minus league avg, per position. **Positive = champions pay up; negative = value.**
- `cap_pct` / `avg_cap_pct` — share of a team's cap spent at a position (0–1; format as %).
- `net_epa_play` — offense EPA/play minus defense EPA/play allowed (higher = better).
- `value_index` — a player's caliber percentile minus pay percentile (higher = more underpaid for the production).

## Build it

See [`BUILD_GUIDE.md`](BUILD_GUIDE.md) for the click-by-click: install Tableau Public
(free), connect the CSVs, build four worksheets, assemble the dashboard, and publish
to a public URL.
