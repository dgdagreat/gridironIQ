# 🏈 GridironIQ

> **In the salary cap era, which positions truly win championships — and are teams paying for it correctly?**

GridironIQ is a full-stack NFL analytics platform built around that one question.
It models three decades of salary-cap data as **share of the cap** (not raw
dollars), correlates positional spending with Super Bowl outcomes, and uses
machine learning to find the roster-construction profiles that actually win — then
flips to the field with a **Film Room** that explains *why a team lost* in plain,
tactical language.

Three products, one thesis:

| | |
|---|---|
| **📊 Boardroom — Cap Efficiency Analyzer** | Where the money goes, and whether it buys rings. Positional cap shares 1994→present, era-segmented, correlated with Super Bowl appearances/wins, with a scikit-learn pipeline (cross-validation + feature importance) and k-means roster archetypes. |
| **🎬 Film Room — Post-Game Breakdown** | Why a team lost. Pulls nflfastR play-by-play, extracts tactical metrics (pressure, EPA, red-zone, turnovers, YAC), and uses the Anthropic API (`claude-sonnet-4-6`) to write a film-room report. |
| **🏆 Super Bowl Maxer** | How far is a team's *current* roster from a champion's? Scores every live roster (production + external grade, age/trend-adjusted) against a champion blueprint weighted by the Boardroom's findings → readiness score, league rank, ranked needs, and the **best available free agents** to fill them. Refreshes daily so it tracks signings, trades, and cuts. |

---

## The thesis, in early numbers

Computed by this pipeline over the **reliable modern window (2011–2024)**, where
the OverTheCap source is comprehensive (see [Data & methodology](#data--methodology)).
Shares are *normalized* (a position's slice of a team's accounted cap), so eras
with different coverage stay comparable.

**Champion premium** — SB-winner average share minus league average, by position:

| Verdict | Positions | Read |
|---|---|---|
| 💚 **Worth paying up** (champions over-index *and* spend tracks winning) | **TE, QB, EDGE, S** | TE is the strongest single signal (corr with winning ≈ 0.16); QB and a premium pass rush follow. |
| ⚪ **Fairly paid** | WR, IDL, Specialists | Roughly neutral — spend here tracks neither way. |
| 🔴 **Overpaid leaguewide** (champions *under*-index, weak/negative correlation) | **RB, CB, LB, OL** | Matches the modern analytics consensus on running backs; off-ball LB and big CB rooms don't correlate with titles. |

**Winning archetypes** (k-means on spending profiles): the **"QB + S"** build —
above-average investment in quarterback and safety — has the **highest title rate
(~5.8%)**, while **"RB + EDGE"** and **"IDL + CB"** builds win least.

**Predicting the Super Bowl** from a team's positional-spending profile alone:
a random forest reaches **~0.71 cross-validated ROC-AUC for predicting SB *wins***,
with **TE and WR cap share** the most important features by permutation importance.

> ⚠️ These are directional findings from a hard problem (only ~14 champions in the
> window) — signals, not destiny. They are reproducible end-to-end: `python scripts/run_cap_etl.py`
> then `python -m gridiron.modeling.cap_efficiency`.

---

## Architecture

Clean separation between **ingestion**, **modeling**, and **frontend**, with a
SQL layer as the shared source of truth.

```
gridironIQ/
├── gridiron/                  # Python package
│   ├── config.py              # paths, era milestones, league-cap reference, data URLs
│   ├── db.py                  # SQLite access layer (SQLAlchemy)
│   ├── ingestion/
│   │   ├── reference.py       # teams, position groups, Super Bowl results
│   │   ├── cap_data.py        # OTC/nflverse contracts → positional spending shares
│   │   ├── load_cap.py        # cap ETL orchestration → SQLite
│   │   └── rosters.py         # live rosters + Madden/AV talent grades (Maxer)
│   ├── modeling/
│   │   ├── cap_efficiency.py  # champion premium, spend↔success correlation, verdicts
│   │   ├── ml_pipeline.py     # sklearn SB-probability model (CV + feature importance)
│   │   ├── clustering.py      # k-means roster archetypes
│   │   ├── roster_strength.py # per-team per-position strength rankings (Maxer)
│   │   ├── sb_maxer.py        # champion blueprint + gap/readiness/needs (Maxer)
│   │   └── free_agents.py     # best available FAs to fill each team's needs (Maxer)
│   └── filmroom/
│       ├── pbp_metrics.py     # nflfastR play-by-play → tactical metrics
│       └── breakdown.py       # Anthropic claude-sonnet-4-6 film report
├── sql/
│   ├── 01_schema.sql          # canonical data model (tables)
│   └── 02_views.sql           # analytical views + indexes
├── scripts/
│   ├── run_cap_etl.py         # CLI: build the Boardroom cap layer
│   └── refresh_rosters.py     # CLI: refresh the Maxer roster layer (daily-scheduled)
├── app/streamlit_app.py       # working frontend (Boardroom + Film Room + Maxer tabs)
├── frontend/                  # planned React build (see frontend/README.md)
├── data/                      # raw + processed artifacts, SQLite db (git-ignored)
└── notebooks/
```

---

## Quickstart

Requires Python 3.10+ ([`uv`](https://github.com/astral-sh/uv) recommended; native
3.11 is the tested target).

```bash
# 1. Environment
uv venv --python 3.11 .venv
uv pip install -e .                 # installs deps + the gridiron package (editable)

# 2. Build the Boardroom data layer (downloads contracts, loads SQLite)
python scripts/run_cap_etl.py

# 3. See the analysis from the command line
python -m gridiron.modeling.cap_efficiency     # champion premium + verdicts
python -m gridiron.modeling.ml_pipeline        # SB-probability model + importances
python -m gridiron.modeling.clustering         # roster archetypes

# 4. Build the Super Bowl Maxer layer (live rosters + talent grades)
python scripts/refresh_rosters.py

# 5. Launch the app (Boardroom + Maxer live; Film Room needs step 6)
streamlit run app/streamlit_app.py

# 6. (Film Room) add your key
cp .env.example .env   # then set ANTHROPIC_API_KEY
```

The Maxer roster layer is refreshed **daily** by a `launchd` agent
(`~/Library/LaunchAgents/com.gridironiq.refresh.plist`) so it tracks NFL churn.
Inspect/remove it with:

```bash
launchctl print  gui/$(id -u)/com.gridironiq.refresh     # status
launchctl bootout gui/$(id -u)/com.gridironiq.refresh    # disable
```

---

## The ETL pipeline

`scripts/run_cap_etl.py` → `gridiron.ingestion.load_cap.run_etl()` runs an
idempotent, fully-documented pipeline:

```
download_contracts        nflverse historical_contracts release  → data/raw/*.parquet
  └─ build_player_year_caps   explode nested per-year cap detail  → 1 row / player / season
       └─ _select_governing_contract   de-dup overlapping deals   → the cap charge that counted
            └─ build_positional_spending  aggregate + normalize    → team × season × position
                 └─ build_spending_features  pivot wide            → model-ready matrix
                      └─ load to SQLite (schema → tables → views)
```

Re-running drops and rebuilds every table, so the Boardroom layer fully refreshes
each run.

### Data model (SQLite)

| Table | Grain | Notes |
|---|---|---|
| `league_cap` | season | League cap + era + milestone (the share denominator) |
| `super_bowls` / `team_outcomes` | season / team-season | SB participants + tidy `sb_appearance`/`sb_win` target |
| `player_year_caps` | player-season | Exploded, de-duplicated cap charges |
| `positional_spending` | team-season-position | `cap_pct`, `cap_pct_norm`, dollars, player counts |
| `spending_features` | team-season | Wide `pct_<POS>` matrix for ML |
| `v_team_season` (view) | team-season | Features joined to the SB target |
| `v_position_success` (view) | position | The champion-premium headline |

---

## Data & methodology

**Sources.** Salary-cap/contract data comes from the
[nflverse](https://github.com/nflverse/nflverse-data) `historical_contracts`
release (sourced from [OverTheCap](https://overthecap.com)); play-by-play comes
from the nflverse `pbp` release (nflfastR). Both are read directly as versioned
parquet assets — no fragile scraping, no heavyweight client library.

**Cap *share*, not dollars.** Every comparison is a position's cap charge as a
fraction of the cap, so 1995 and 2024 are on the same axis. We take each
contract-year's own `cap_percent` and cross-check it against
`dollars / league_cap`.

**Governing-contract de-duplication.** `historical_contracts` stores *every* deal
a player ever signed, each projecting a full multi-year cap schedule — so an
extension and the deal it replaced both carry the overlap years. We attribute each
player-season to the **most recently signed contract in effect** that season,
eliminating the double-counting (which otherwise inflates modern-era spend to
>400% of the cap).

**Era segmentation.** The thesis cares about structural breaks, flagged as
milestones and used to bucket every season:

- **1994** — salary cap introduced (start of the analysis window)
- **2004** — defensive-contact rule emphasis (illegal contact / defensive holding)
- **2011** — CBA (rookie wage scale, restructured cap mechanics)
- **2021** — 17-game regular season

**Known limitation — historical coverage.** The OTC source is comprehensive from
**~2011 onward** (it captures ~77–80% of each team's cap; the remainder is dead
money / minimum deals). **Before 2011 it is sparse** (only ~10–17% of cap
captured), so pre-2011 positional *distributions* are directional at best. The
modeling layer therefore defaults to the **2011–2024** window, and the normalized
share keeps eras comparable. (Pleasingly, the 2011 CBA is both a rule milestone
*and* the data-quality boundary.)

**Honest about what's charted.** The Film Room computes what play-by-play
genuinely supports (EPA, pressure via `qb_hit`/`sack`, turnovers, red-zone and
down efficiency, YAC). True **WR separation** and **yards after contact** are
charting feeds (NGS / PFR) wired in a later pass — surfaced as "not charted"
rather than faked.

---

## Super Bowl Maxer methodology

The Maxer is the Boardroom turned **prescriptive** — it reuses the same position
groups and the same win-importance signal, then applies them to *current* rosters.

**Talent = production + external grade, then age- and trend-adjusted.** Each
player on the live roster is scored by blending **PFR Approximate Value**
(production) with the **Madden overall** (external grade), each percentile-ranked
within its position group. Both are all-position signals joined by `gsis_id`, so
the trenches and secondary — where box stats lie — still get a fair grade.
Position groups come from the granular `depth_chart_position` (so EDGE/IDL and
CB/S stay split). A static grade is **not** taken as gospel: it's discounted by a
**position-aware age curve** (talent falls each year past a position's peak — a
QB ages differently than a running back) and by a **3-season production trend**
(AV trajectory), so an aging, declining star is graded as one — not as his prime
self. (Example: a 37-year-old TE with a 93 Madden and falling AV scores ~0.64,
not 1.0.)

**Strength → blueprint → gap.** A team's unit at each position is the mean talent
of its top *k* players, percentile-ranked vs. the 32 teams (0–100). The champion
**blueprint** sets a target percentile per position, scaled by that position's
Boardroom win-importance (be elite at QB/TE/EDGE, merely adequate at RB/LB). The
**gap** is the weighted shortfall; **readiness** (0–100), **league rank**, and the
**ranked needs** all fall out of it.

**Free-agent recommender.** A free agent is defined live as *last season's player
not on any current roster* — so it re-derives every refresh as teams sign people.
The pool is scored with the same age/trend-adjusted talent model, and for each of
a team's top needs the best available players are surfaced (e.g. an aging WR with
a high Madden but falling production ranks below a younger riser). It's a concrete
shopping list, not just a diagnosis.

**Freshness is the whole point.** Rosters are pulled live from nflverse (so trades,
cuts, and signings appear), grades from the maintained
[nfl-madden-data](https://github.com/theedgepredictor/nfl-madden-data) repo. Every
download is cached with a TTL and re-fetchable (`--force`); each output is stamped
`data_as_of`. A `launchd` agent runs `scripts/refresh_rosters.py` **daily** (and
catches up on wake), so nothing is ever hardcoded or stale.

---

## Status

| Component | State |
|---|---|
| Project scaffold + SQL model | ✅ complete |
| Cap ETL (download → de-dup → aggregate → load) | ✅ complete & validated (1994–2024, 32 teams) |
| Boardroom: cap-efficiency analysis | ✅ runs on live data |
| Boardroom: ML pipeline (CV + importance) | ✅ baseline (~0.71 AUC for SB wins) |
| Boardroom: roster-archetype clustering | ✅ runs on live data |
| Film Room: pbp metric extraction | ✅ validated live (Super Bowl LX) |
| Film Room: Anthropic breakdown | 🟡 wired; needs `ANTHROPIC_API_KEY` to generate |
| **Super Bowl Maxer** (roster → strength → needs) | ✅ live (2026 rosters, 32 teams; age/trend-adjusted) |
| Maxer: free-agent needs recommender | ✅ live (re-derives FA pool each refresh) |
| Maxer daily refresh (launchd) | ✅ installed & scheduled |
| Streamlit app (3 tabs) | ✅ Boardroom + Maxer live; Film Room wired |
| Charting metrics (separation, YACO) | 🟡 scaffolded (NGS/PFR pass) |
| React frontend | 📋 planned ([frontend/README.md](frontend/README.md)) |

---

## Tech stack

Python · pandas · scikit-learn · matplotlib/seaborn · SQLite (SQLAlchemy) ·
Streamlit · Anthropic API (`claude-sonnet-4-6`) · launchd (daily refresh) ·
data: nflverse/OverTheCap · nflfastR · [nfl-madden-data](https://github.com/theedgepredictor/nfl-madden-data).
