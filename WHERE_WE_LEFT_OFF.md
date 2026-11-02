# GridironIQ — where we left off (handoff for the new session)

_Last updated: 2026-11-02._

## Setup (do this first)
Project lives at `~/dev/gridironIQ` (moved off iCloud-synced Desktop — `fileproviderd`
was pinning the machine). A moved venv has stale absolute paths, so if `.venv` looks off:

```bash
cd ~/dev/gridironIQ && rm -rf .venv && uv venv && uv pip install -r requirements.txt
```

- Run anything with `PYTHONPATH=. .venv/bin/python …` (gridiron isn't pip-installed).
- `.venv` is uv-managed Python 3.11; no bare `python`.
- **Deploys:** push to `main` → Streamlit Cloud redeploys `gridironiq-nfl.streamlit.app`.
  **It often lags a commit behind** — force it with **Manage app → Reboot** in the
  Streamlit Cloud dashboard (see the deploy note below).
- `data/gridiron.db` is a TRACKED SQLite snapshot the app reads (`git add` it after a refresh).
- `gh` CLI is now installed (`brew`) and authenticated as `dgdagreat`, so you can
  `gh pr create` / `gh pr merge` from the shell.

## This session (2026-11-02) — shipped to `main`
Working branch: `fix/daily-roster-commit-back`. Three PRs merged:

- **PR #1** (merge `deaa2c9`) — Boardroom **Team spending profile** upgrades:
  - `e217902` **Position ↔ Individual player** toggle (breaks the cap down by player;
    `positional_spending` is just `player_year_caps` summed, so the two reconcile).
  - `41771ab` **"vs. the Super Bowl champion blueprint"** comparison: a **radar overlay**
    (team cap shape over the champion average) beside a **diverging delta bar**.
  - (PR #1 was a broad umbrella that also carried others' commits — the React/FastAPI
    frontend `37be73d` and review-fixes `28493cc`, plus the line-chart "Compare cap
    efficiency" multiselect that sits above the radar/bar in the Boardroom.)

- **PR #2** (merge `88a738b`, commit `debe82b`) — four features:
  1. **Season default → current, rolls over every August.** New `config.DEFAULT_SEASON`
     (`year` if month ≥ 8 else `year-1`; `CURRENT_SEASON` stays March-based for the
     pipeline). Boardroom + Film Room selectors default to it.
  2. **Division preset** for the cap comparison — `reference.DIVISIONS` / `TEAM_DIVISION`
     + a "Division" picker that loads a division's four teams into the compare.
  3. **Film Room play-by-play by quarter** — the detail expander groups into Q1–Q4/OT
     with per-offense subtotals and a game total.
  4. **Live free-agent roster builder** in the Maxer — sign FAs, injected as starters,
     recompute field/grades/outlook/rank/needs live (`_sim_roster_strength`).

- **PR #3** (merge `ccef369`, commit `f18a69e`) — **trade market board**:
  - New `gridiron/modeling/trade_market.py`: estimates a rostered player's trade value
    in **draft-pick terms** = caliber (`talent`, convex) × market positional premium
    (QB → specialists, `TRADE_POS_MULT`) × age factor, mapped onto the **Jimmy Johnson**
    pick chart → a tier ("1st round (top-10)" … "minimal"). `trade_board()` surfaces
    acquirable players (on other rosters) at a team's needs.
  - Maxer "Build your team" → **two click-to-select boards** (`st.dataframe` `on_select`):
    🟢 Free agents (click to sign, cap cost) and 🔄 Trade targets (click to trade for,
    pick cost). **Dropdown removed.** Trades are *moved off* their old roster;
    `_sim_roster_strength(team, signed, traded)`. Combined cap/pick summary + deltas.

## ⚠️ Open: PR #3 trade board not confirmed live yet
PR #3 is merged to `main` and fully verified **locally**, but at last check the hosted
app was still serving the PR #2 build (old FA dropdown, no Trade targets board).
**Reboot the Streamlit Cloud app** to force the new commit, then verify the Maxer shows
the two click-to-select boards (🟢 Free agents | 🔄 Trade targets). Deploy lag + reboot
was the recurring pattern all session.

## Next steps / ideas
- **trade_market v2:** factor the player's **contract/cap** into trade value (join `apy`
  from `value_board`/`free_agents`); optionally a modern (flatter) pick chart; model the
  acquiring side actually *sending* picks/players.
- Boardroom has **two overlapping cap-comparison UIs** now (the line-chart "Compare cap
  efficiency" multiselect from PR #1's umbrella, and the radar/blueprint comparison) —
  worth consolidating.
- Earlier idea still open: snaps/matchup/opponent-adjusted features; a real OL grade.

## Context: player-value ML grades the whole roster (already on main)
Both learned models are live, wired into the in-season grades (`perf_raw` override →
percentile-within-pos_group → lift-biased blend). ~892 players model-graded.
- `b2c64b4` **skill model** `gridiron/modeling/player_value.py` (rest-of-season fantasy
  PPR/g; R²=0.68 vs 0.59 baseline).
- `9bc11be` **defense model** `gridiron/modeling/defense_value.py` (IDP box score;
  R²=0.432 vs 0.210). Disruption plays carry signal above tackle volume.
- Trains strictly before the target (no leakage); degrades to the hand-tuned composite
  per group. OL/specialists always use the composite. Injured players fall back to static.

## Gotchas
- Do NOT commit `.claude/launch.json` (machine-specific). `WHERE_WE_LEFT_OFF.md` is kept
  **untracked** (local handoff note) — it's been deliberately left out of commits.
- Streamlit no-TTL `@st.cache_data` + a cache-busting guard keyed on DB mtime: new *data*
  shows once the db mtime changes; new *code* needs the container to restart (reboot).
- Benign console noise: Plotly SVG warnings (`<text> y=-Infinity`, `<rect> width=-42`)
  from the Boardroom charts — `st.tabs` renders every tab each run, so they show on any
  tab. Not from the dataframe boards; nothing breaks.
- Machine is 8GB — keep the project OUT of iCloud. Turn off iCloud "Desktop & Documents".
