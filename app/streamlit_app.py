"""
GridironIQ — Streamlit frontend.

Two clearly separated tabs:
  * Boardroom  — cap-efficiency analytics over the loaded SQLite model (live).
  * Film Room  — post-game breakdown via play-by-play metrics + Anthropic.

Run from the project root:
    streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Put the repo root on the path so `gridiron` imports even when the app is run
# with a Streamlit that doesn't have the package editable-installed.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

from gridiron import config, db
from gridiron.modeling import (cap_efficiency, clustering, free_agents, sb_maxer,
                               value_board)

st.set_page_config(page_title="GridironIQ", page_icon="🏈", layout="wide")

# Bust all cached DB reads when the data snapshot changes under the app. Every
# @st.cache_data loader below has no TTL, so after a redeploy ships a fresh
# data/gridiron.db the old container keeps serving its cached tables until a full
# reboot — the "No cap data" / stale-grade staleness seen in practice. The DB
# file's mtime changes on each deploy (new checkout), so clearing the cache when
# it moves makes new data appear without waiting on a reboot.
try:
    _db_version = config.DB_PATH.stat().st_mtime
except OSError:
    _db_version = 0.0
if st.session_state.get("_db_version") != _db_version:
    st.cache_data.clear()
    st.session_state["_db_version"] = _db_version

THESIS = ("In the salary cap era, which positions truly win championships — "
          "and are teams paying for it correctly?")


# --------------------------------------------------------------------------- #
# Cached data access
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def _champion_premium() -> pd.DataFrame:
    return cap_efficiency.champion_premium().reset_index()


@st.cache_data(show_spinner=False)
def _verdict() -> pd.DataFrame:
    return cap_efficiency.efficiency_verdict().reset_index()


#: Full position names for display (match the Tableau dashboard's labels).
_POS_FULL = {"QB": "Quarterback", "RB": "Running Back", "WR": "Wide Receiver",
             "TE": "Tight End", "OL": "Offensive Line", "IDL": "Interior D-Line",
             "EDGE": "Edge Rusher", "LB": "Linebacker", "CB": "Cornerback",
             "S": "Safety", "SPEC": "Special Teams"}


def _premium_fig(prem: pd.DataFrame):
    """Diverging horizontal bar of champion premium by position — mirrors the
    live Tableau dashboard: green = champions pay up, orange = value, sorted
    with percentage labels and the same headline."""
    import plotly.graph_objects as go

    d = prem.copy()
    d["position"] = d["pos_group"].map(_POS_FULL).fillna(d["pos_group"])
    d["pp"] = d["premium"] * 100                     # fraction of cap -> points
    d = d.sort_values("premium")                     # ascending -> TE lands on top
    pay_up = d["premium"] > 0
    fig = go.Figure(go.Bar(
        x=d["pp"], y=d["position"], orientation="h",
        marker_color=["#1a7f37" if up else "#d4691e" for up in pay_up],
        text=[f"{v:+.2f}%" for v in d["pp"]], textposition="outside",
        cliponaxis=False,
        hovertemplate="%{y}: %{x:+.2f} pts of cap vs league avg<extra></extra>"))
    fig.update_layout(
        title=dict(text="Where Super Bowl winners overspend", font=dict(size=18)),
        xaxis_title="Champion cap share − league average (percentage points)",
        yaxis_title=None, height=420, showlegend=False,
        plot_bgcolor="white", font=dict(size=13),
        margin=dict(l=10, r=48, t=52, b=36))
    fig.update_xaxes(ticksuffix="%", gridcolor="#eef1f3", zeroline=True,
                     zerolinecolor="#c9ced4", zerolinewidth=1)
    fig.update_yaxes(ticksuffix="  ")
    return fig


@st.cache_data(show_spinner=False)
def _team_season(team: str, season: int) -> pd.DataFrame:
    return db.query(
        "SELECT pos_group, cap_pct, cap_pct_norm, n_players FROM positional_spending "
        "WHERE team = :t AND season = :s ORDER BY cap_pct_norm DESC",
        t=team, s=season,
    )


@st.cache_data(show_spinner=False)
def _seasons_teams() -> tuple[list[int], list[str]]:
    df = db.query("SELECT DISTINCT season, team FROM positional_spending")
    # Native Python ints — not np.int64 — so season comparisons and DB binds work.
    return (sorted((int(s) for s in df["season"].unique()), reverse=True),
            sorted(df["team"].unique()))


@st.cache_data(show_spinner=True)
def _archetypes(k: int):
    res = clustering.cluster_archetypes(k=k)
    return res.success.join(res.profiles["label"]).reset_index(), res.profiles.reset_index()


@st.cache_data(show_spinner=False)
def _roster_strength() -> pd.DataFrame:
    return db.read_table("roster_strength")


@st.cache_data(show_spinner=False)
def _maxer_meta() -> dict:
    return db.read_table("maxer_meta").iloc[0].to_dict()


@st.cache_data(show_spinner=False)
def _free_agents() -> pd.DataFrame:
    return db.read_table("free_agents")


@st.cache_data(show_spinner=False)
def _player_talent() -> pd.DataFrame:
    return db.read_table("player_talent")


@st.cache_data(show_spinner=False)
def _prior_rank(season: int) -> dict:
    """team -> where it finished `season` (regular-season record rank)."""
    df = sb_maxer.prior_season_rank(season)
    return dict(zip(df["team"], df["prev_rank"])) if not df.empty else {}


# --------------------------------------------------------------------------- #
# Boardroom
# --------------------------------------------------------------------------- #
def boardroom_tab() -> None:
    if not db.table_exists("spending_features"):
        st.warning("No data loaded yet. Run the ETL first:\n\n"
                   "```\npython scripts/run_cap_etl.py\n```")
        return

    st.subheader("The headline: do champions over- or under-pay by position?")
    st.caption("Normalized cap share among Super Bowl winners minus the league "
               "average (2011–2024, where the OverTheCap source is comprehensive). "
               "Positive = champions invest *more* here; negative = they win "
               "spending *less*.")

    prem = _champion_premium()
    col1, col2 = st.columns([3, 2])
    with col1:
        st.plotly_chart(_premium_fig(prem), use_container_width=True)
    with col2:
        vdf = _verdict().copy()
        if "champion_premium" in vdf:
            vdf["champion_premium"] = vdf["champion_premium"] * 100
        st.dataframe(vdf, hide_index=True, height=420, column_config={
            "pos_group": st.column_config.TextColumn("Pos"),
            "champion_premium": st.column_config.NumberColumn(
                "Champ premium", format="%+.2f%%",
                help="Champion avg cap share minus league average (percentage points)"),
            "corr_win": st.column_config.NumberColumn("Corr. w/ wins", format="%.3f"),
            "verdict": st.column_config.TextColumn("Verdict"),
        })

    st.divider()
    st.subheader("Team spending profile")
    st.caption(f"Positional cap allocation by season — history from "
               f"{config.START_SEASON}, projected out to {config.PROJECTION_SEASON} "
               "using cap already committed on signed multi-year deals.")
    seasons, teams = _seasons_teams()
    c1, c2 = st.columns(2)
    team = c1.selectbox("Team", teams, key="br_team",
                        index=teams.index("KC") if "KC" in teams else 0)
    # Default to the latest season with on-field results (EPA) so both the
    # spending chart and the "did it translate?" EPA panel populate on open;
    # the current year only has committed-money projections and no results yet.
    _epa_seasons = (sorted(db.query("SELECT DISTINCT season FROM pbp_team_season_epa")["season"])
                    if db.table_exists("pbp_team_season_epa") else [])
    _complete = [s for s in _epa_seasons if s in seasons]
    _def_season = (max(_complete) if _complete
                   else config.CURRENT_SEASON if config.CURRENT_SEASON in seasons
                   else seasons[0])
    season = c2.selectbox("Season", seasons, index=seasons.index(_def_season),
                          key="br_season")
    if season > config.CURRENT_SEASON:
        st.info(f"⏳ **{season} is a projection** — only cap already tied up in "
                "signed multi-year contracts. Rosters aren't full this far out, so "
                "shares reflect *committed* money, not a complete team.")
    prof = _team_season(team, season)
    if prof.empty:
        if season > config.CURRENT_SEASON:
            st.info(f"No cap committed to {team} for {season} yet — no current "
                    "contract on the books runs that far out.")
        else:
            st.info(f"No cap data for {team} in {season}.")
    else:
        left, right = st.columns([3, 2])
        left.plotly_chart(_spending_chart(prof, team, season), use_container_width=True)
        right.dataframe(prof, hide_index=True, height=340, column_config={
            "pos_group": st.column_config.TextColumn("pos"),
            "cap_pct": st.column_config.NumberColumn("cap %", format="percent"),
            "cap_pct_norm": st.column_config.NumberColumn("of team", format="percent"),
            "n_players": st.column_config.NumberColumn("players"),
        })

    # On-field efficiency from the PBP lakehouse (nflfastR EPA, built by the Spark
    # medallion and published to the app db). Did the cap allocation translate?
    if db.table_exists("pbp_team_season_epa"):
        epa = db.query("SELECT * FROM pbp_team_season_epa WHERE season = :s", s=season)
        if not epa.empty and (epa["team"] == team).any():
            r = epa.set_index("team").loc[team]
            rank = int((epa["net_epa_play"] > r["net_epa_play"]).sum()) + 1
            st.caption("On-field efficiency from the **PBP lakehouse** "
                       "(nflfastR EPA via the Spark medallion) — did the cap "
                       "allocation translate to results?")
            e1, e2, e3 = st.columns(3)
            e1.metric("Off. EPA/play", f"{r['off_epa_play']:+.3f}")
            e2.metric("Def. EPA/play allowed", f"{r['def_epa_play_allowed']:+.3f}")
            e3.metric("Net EPA/play", f"{r['net_epa_play']:+.3f}")
            st.caption(f"Net EPA/play ranks **#{rank} of {len(epa)}** teams in {season}.")

    st.divider()
    st.subheader("Winning roster archetypes (k-means on spending profiles)")
    k = st.slider("Number of archetypes", 3, 7, 5)
    success, profiles = _archetypes(k)
    st.caption("Each team-season clustered by its positional spending; archetypes "
               "labeled by their most *distinctive* investments and scored by title rate.")
    st.dataframe(success, hide_index=True, column_config={
        "n_team_seasons": st.column_config.NumberColumn("team-seasons"),
        "sb_appearance_rate": st.column_config.NumberColumn("SB appearance", format="percent"),
        "sb_win_rate": st.column_config.NumberColumn("SB win", format="percent"),
    })
    with st.expander("Archetype spending profiles"):
        st.dataframe(profiles, hide_index=True)


# --------------------------------------------------------------------------- #
# Film Room — every game, pre & post
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def _schedule(season: int) -> pd.DataFrame:
    from gridiron.ingestion import schedules
    return schedules.list_games(season)


@st.cache_data(show_spinner=True)
def _pbp(season: int):
    from gridiron.filmroom import pbp_metrics
    return pbp_metrics.load_pbp(int(season))


def _run_report(breakdown, payload: dict) -> None:
    try:
        with st.spinner(f"Writing the report with {config.ANTHROPIC_MODEL}…"):
            st.markdown(breakdown.generate_breakdown(payload))
    except Exception as exc:  # noqa: BLE001 - surface API/key errors in the UI
        st.error(f"Generation failed: {exc}")


def film_room_tab() -> None:
    from gridiron.filmroom import breakdown, matchup, pbp_metrics

    st.subheader("Film Room — every game, pre & post")
    st.caption("Completed games get a post-game breakdown ('why they lost'); "
               "upcoming games get a matchup preview from form + roster edges. "
               f"`{config.ANTHROPIC_MODEL}` writes the report (needs `ANTHROPIC_API_KEY`); "
               "play-by-play (~40 MB/season) loads on first use.")

    c1, c2 = st.columns(2)
    season = c1.selectbox("Season", [2026, 2025, 2024, 2023], index=0, key="fr_season")
    try:
        sched = _schedule(int(season))
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not load schedule: {exc}")
        return
    week = c2.selectbox("Week", sorted(sched["week"].unique()), index=0, key="fr_week")

    wk = sched[sched["week"] == week].copy()
    wk["label"] = wk.apply(
        lambda r: f"{r.away_team} @ {r.home_team}" + (
            f"  ({int(r.away_score)}–{int(r.home_score)})" if r.status == "played"
            else "  · scheduled"), axis=1)
    game = wk[wk["label"] == st.selectbox("Game", wk["label"], key="fr_game")].iloc[0]

    # Loading play-by-play (~40 MB) is heavy, and st.tabs runs *every* tab on each
    # rerun — so gate it behind a click to keep the whole app painting instantly.
    if st.button("Load this game", type="primary", key="fr_load"):
        st.session_state["fr_loaded"] = game["game_id"]
    if st.session_state.get("fr_loaded") != game["game_id"]:
        st.caption("Pick a game above and click **Load this game** to pull its data.")
        return

    if game["status"] == "played":
        with st.spinner(f"Loading {season} play-by-play…"):
            pbp = _pbp(int(season))
        payload = pbp_metrics.build_breakdown_payload(pbp, game["game_id"])
        lo = payload["losing_offense"]
        st.markdown(f"**{payload['winner']} def. {payload['loser']}** — "
                    f"why {payload['loser']} lost")
        m = st.columns(4)
        m[0].metric(f"{payload['loser']} EPA/play", lo["epa_per_play"])
        m[1].metric("Pass EPA", lo["pass_epa"])
        m[2].metric("Sacks allowed", lo["sacks_allowed"])
        m[3].metric("Turnovers", lo["turnovers"])
        with st.expander("Extracted metrics + player attribution"):
            st.json(payload)
        if st.button("Generate post-game breakdown", type="primary"):
            _run_report(breakdown, payload)
    else:
        form_season = int(season) - 1   # offseason: last completed season's form
        with st.spinner(f"Loading {form_season} form…"):
            form_pbp = _pbp(form_season)
        strength = _roster_strength() if db.table_exists("roster_strength") else None
        payload = matchup.build_preview_payload(
            game["home_team"], game["away_team"], form_pbp=form_pbp,
            form_season=form_season, week=int(game["week"]), roster_strength=strength)
        st.markdown(f"**{game['away_team']} @ {game['home_team']}** — "
                    f"matchup preview (form: {form_season})")
        if payload["roster_edges"]:
            h, a = game["home_team"], game["away_team"]
            st.caption(f"Biggest roster-strength edges — position grades for "
                       f"{h} (home) vs {a} (away). Edge = home − away percentile.")
            edf = pd.DataFrame(payload["roster_edges"]).head(6)
            edf[h] = edf["home"].map(_grade)
            edf[a] = edf["away"].map(_grade)
            st.dataframe(_style_grades(edf[["pos_group", h, a, "edge"]], [h, a]),
                         hide_index=True)
        with st.expander("Team form + edges"):
            st.json(payload)
        if st.button("Generate matchup preview", type="primary"):
            _run_report(breakdown, payload)


#: Position groups → unit, for coloring the cap-allocation chart. Lets the O/D
#: cap balance read at a glance on top of the per-position shares.
_POS_UNIT = {
    "QB": "Offense", "RB": "Offense", "WR": "Offense", "TE": "Offense", "OL": "Offense",
    "IDL": "Defense", "EDGE": "Defense", "LB": "Defense", "CB": "Defense", "S": "Defense",
    "SPEC": "Special teams",
}
#: Unit colors — validated CVD-safe on the app's light surface (dataviz validator:
#: adjacent ΔE 20.8 deutan, all ≥ 3:1 contrast).
_UNIT_COLOR = {"Offense": "#1a9850", "Defense": "#2b6cb0", "Special teams": "#a86a00"}


def _spending_chart(prof: pd.DataFrame, team: str, season: int):
    """Horizontal, sorted bar of a team's cap allocation by position group.

    A sorted bar beats a pie for this: ~11 categories read as length (precise)
    rather than angle/area (not), the ranking of spending priorities is immediate,
    and every label stays legible. Bars are colored by unit (offense / defense /
    special teams) so the offense-vs-defense cap balance also reads at a glance.
    """
    import plotly.graph_objects as go
    d = prof.copy()
    d["unit"] = d["pos_group"].map(_POS_UNIT).fillna("Special teams")
    d = d.sort_values("cap_pct_norm", ascending=True)      # largest lands on top
    order = d["pos_group"].tolist()

    fig = go.Figure()
    for unit, color in _UNIT_COLOR.items():
        sub = d[d["unit"] == unit]
        if sub.empty:
            continue
        fig.add_bar(
            x=sub["cap_pct_norm"], y=sub["pos_group"], name=unit, orientation="h",
            marker_color=color, cliponaxis=False,
            text=[f"{v:.0%}" for v in sub["cap_pct_norm"]], textposition="outside",
            textfont=dict(color="#222", size=11),
            customdata=sub[["cap_pct", "n_players"]].to_numpy(),
            hovertemplate=("<b>%{y}</b> · " + unit +
                           "<br>%{x:.1%} of the team's cap"
                           "<br>%{customdata[0]:.1%} of the league cap · "
                           "%{customdata[1]} players<extra></extra>"),
        )
    xmax = float(d["cap_pct_norm"].max() or 0) * 1.18 or 1.0
    fig.update_layout(
        barmode="stack", height=360, bargap=0.28,
        margin=dict(t=46, b=10, l=10, r=20),
        title=dict(text=f"{team} {season} — cap share by position",
                   x=0, xanchor="left", font=dict(size=14)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    font=dict(size=11), title=None),
        xaxis=dict(tickformat=".0%", range=[0, xmax], showgrid=True,
                   gridcolor="rgba(0,0,0,0.06)", zeroline=False, title=None),
        yaxis=dict(categoryorder="array", categoryarray=order, title=None),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def _grade(pctile: float) -> str:
    """0–100 percentile → an A–F report-card grade."""
    p = pctile or 0
    return ("A" if p >= 85 else "B" if p >= 70 else "C" if p >= 45
            else "D" if p >= 25 else "F")


#: Grade → cell background (green = strong, red = weak) so holes pop.
_GRADE_BG = {"A": "#1a7f37", "B": "#3fb950", "C": "#bf8700",
             "D": "#d4691e", "F": "#cf222e"}


def _style_grades(df: pd.DataFrame, cols: list[str]):
    """Return ``df`` as a Styler with A–F grade cells shaded green→red."""
    return df.style.map(
        lambda v: f"background-color: {_GRADE_BG.get(v, '')}; color: white"
        if v in _GRADE_BG else "", subset=cols)


# --------------------------------------------------------------------------- #
# Interactive football field (the Maxer's headline visual)
# --------------------------------------------------------------------------- #
#: The base personnel most NFL teams actually run — **11-personnel shotgun**
#: offense (1 RB, 1 TE, 3 WR) against a **nickel** defense (4 down, 2 LB, 5 DB),
#: drawn vertically (offense at the bottom, driving up). Each slot is filled with
#: the team's likely starter there (see :func:`_assign_starters`) and shaded by
#: its position **group** grade. Tuple = ``(role, group, x, y, dcp_bucket)`` with
#: x = field width (0–53.3), y = field length (offense LOS ≈ 44); ``dcp_bucket``
#: pins a slot to a granular ``depth_chart_position`` (a 'T' at tackle, an 'FS' at
#: free safety) so the right player lands there — ``None`` fills by talent order.
_FORMATION: list[tuple[str, str, float, float, str | None]] = [
    # OFFENSE — 11 personnel shotgun (X/Z split wide, slot inside), driving up
    ("X", "WR", 3, 42.5, None), ("Z", "WR", 50, 42.5, None), ("SLOT", "WR", 10, 41, None),
    ("LT", "OL", 16, 44, "T"), ("LG", "OL", 21, 44, "G"), ("C", "OL", 26.5, 44, "C"),
    ("RG", "OL", 32, 44, "G"), ("RT", "OL", 37, 44, "T"),
    ("TE", "TE", 42, 44, None),
    ("QB", "QB", 25, 38, None), ("RB", "RB", 31, 38, None),
    # DEFENSE — nickel (4-2-5): NB (nickel back) is the 3rd CB, over the slot
    ("DE", "EDGE", 15, 47, None), ("DT", "IDL", 22, 47, None), ("DT", "IDL", 31, 47, None),
    ("DE", "EDGE", 38, 47, None),
    ("LB", "LB", 21, 51, None), ("LB", "LB", 32, 51, None),
    ("CB", "CB", 3, 47, None), ("CB", "CB", 50, 47, None), ("NB", "CB", 11, 50, None),
    ("FS", "S", 18, 58, "FS"), ("SS", "S", 35, 58, "SS"),
]


def _assign_starters(team: str, players: pd.DataFrame | None) -> list[dict | None]:
    """Fill each formation slot with this team's likely starter there.

    Players ruled out right now (injured / IR / inactive, ``currently_out``) sort
    to the back, so each slot shows whoever **actually suits up** — the next man up
    when the nominal starter is hurt. The rest are ranked by current depth-chart
    standing (``depth_rank``), then Madden overall. Granular ``depth_chart_position``
    pins players to the right slot (a 'T' at tackle, 'FS'/'SS' at safety); anything
    without a bucket fills by order, so the nickel back is the 3rd corner and the
    slot is the 3rd receiver. The formation is walked in order, consuming players
    so nobody starts twice.
    """
    if players is None or players.empty:
        return [None] * len(_FORMATION)
    tp = players[players["team"] == team].copy()
    tp["_out"] = (tp["currently_out"].fillna(False).astype(bool)
                  if "currently_out" in tp.columns else False)
    sort_cols, asc = ["_out"], [True]
    if "depth_rank" in tp.columns:
        sort_cols.append("depth_rank"); asc.append(True)
    sort_cols += ["madden_ovr", "talent"]; asc += [False, False]
    used: set = set()
    out: list[dict | None] = []
    for _role, grp, _x, _y, bucket in _FORMATION:
        pool = tp[tp["pos_group"] == grp].sort_values(sort_cols, ascending=asc,
                                                       na_position="last")
        buckets = ([pool[pool["depth_chart_position"] == bucket]] if bucket else []) + [pool]
        pick = None
        for cand in buckets:                       # granular slot first, then the group
            for _, row in cand.iterrows():
                if row["gsis_id"] not in used:
                    pick = row
                    break
            if pick is not None:
                break
        if pick is None:
            out.append(None)
            continue
        used.add(pick["gsis_id"])
        out.append({"player": pick["player"], "ovr": pick.get("madden_ovr"),
                    "age": pick.get("age"), "dcp": pick.get("depth_chart_position"),
                    "injured": bool(pick.get("injured_last")),
                    "out_now": bool(pick.get("_out")),
                    "status": pick.get("injury_status")})
    return out


def _field_figure(team: str, strength: pd.DataFrame,
                  players: pd.DataFrame | None = None, highlight: str | None = None):
    """Plotly formation view (vertical): the team's likely **starters** on the
    base most teams run — 11-personnel offense (bottom) vs. a nickel defense
    (top). Each box is the real player at that slot (from ``players`` via
    :func:`_assign_starters`), shaded by its position **group** grade (green
    strong → red weak); hover shows the player. Boxes in the ``highlight`` group
    get a bright gold ring.
    """
    import plotly.graph_objects as go
    rs = strength[strength["team"] == team].set_index("pos_group")
    ranked = strength.assign(
        rk=strength.groupby("pos_group")["strength"].rank(ascending=False, method="min"))
    tr = ranked[ranked["team"] == team].set_index("pos_group")["rk"]
    n = int(strength["team"].nunique())
    starters = _assign_starters(team, players)

    fig = go.Figure()
    fig.add_shape(type="rect", x0=0, x1=53.3, y0=-10, y1=110, layer="below",
                  fillcolor="#2f8f4e", line_width=0)
    for y0, y1 in ((-10, 0), (100, 110)):                    # end zones
        fig.add_shape(type="rect", x0=0, x1=53.3, y0=y0, y1=y1, layer="below",
                      fillcolor="#1c6135", line_width=0)
    for yd in range(0, 101, 5):                              # yard lines (every 5)
        fig.add_shape(type="line", x0=0, x1=53.3, y0=yd, y1=yd, layer="below",
                      line=dict(color="rgba(255,255,255,0.30)",
                                width=2 if yd % 10 == 0 else 1))
    fig.add_shape(type="line", x0=0, x1=53.3, y0=44, y1=44, layer="below",
                  line=dict(color="rgba(255,255,255,0.85)", width=2))  # line of scrimmage

    xs, ys, texts, colors, hovers = [], [], [], [], []
    lcolors, lwidths, sizes = [], [], []
    for i, (label, grp, x, y, _bucket) in enumerate(_FORMATION):
        who = starters[i]
        if grp in rs.index:
            s = float(rs.at[grp, "strength"]); g = _grade(s); rk = int(tr.get(grp, n))
            colors.append(_GRADE_BG[g])
            if who:
                ovr = f"Madden {who['ovr']:.0f}" if pd.notna(who["ovr"]) else "unrated"
                age = f"{who['age']:.0f}" if pd.notna(who["age"]) else "—"
                dcp = who["dcp"] or grp
                if who.get("out_now"):
                    status = who.get("status")
                    inj = f" · 🚑 {status if isinstance(status, str) else 'OUT'}"
                elif who.get("injured"):
                    inj = " · 🩹 credited back from injury"
                else:
                    inj = ""
                hovers.append(f"<b>{who['player']}</b> · {label} ({dcp}){inj}<br>"
                              f"{ovr} · age {age}<br>"
                              f"{grp} unit: grade {g} · #{rk} of {n} in the NFL")
            else:
                hovers.append(f"<b>{label}</b> · {grp} unit · grade {g}<br>"
                              f"#{rk} of {n} · no starter listed")
        else:
            colors.append("#8a8a8a")
            hovers.append(f"{label} · {grp} · no data")
        hot = grp == highlight
        lcolors.append("#ffe14d" if hot else "white")
        lwidths.append(3.5 if hot else 1.4)
        sizes.append(29 if hot else 23)
        xs.append(x); ys.append(y); texts.append(label)
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="markers+text", text=texts, textposition="middle center",
        textfont=dict(color="white", size=9, family="Arial Black"),
        marker=dict(symbol="square", size=sizes, color=colors,
                    line=dict(color=lcolors, width=lwidths)),
        hovertext=hovers, hoverinfo="text"))
    for y, lab in ((33.5, "▼ OFFENSE"), (63, "▲ DEFENSE")):
        fig.add_annotation(x=26.5, y=y, text=lab, showarrow=False,
                           font=dict(color="rgba(255,255,255,0.9)", size=12,
                                     family="Arial Black"))
    fig.update_xaxes(visible=False, range=[-2, 55], fixedrange=True)
    fig.update_yaxes(visible=False, range=[31, 66], fixedrange=True)
    fig.update_layout(height=560, showlegend=False, dragmode=False,
                      margin=dict(l=0, r=0, t=4, b=4),
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    return fig


def _position_detail(pos: str, team: str, strength: pd.DataFrame) -> None:
    """Drill-down card for one position: grade, NFL rank, and best free agents."""
    rs = strength[(strength["team"] == team) & (strength["pos_group"] == pos)]
    n = int(strength["team"].nunique())
    ranked = strength.assign(
        rk=strength.groupby("pos_group")["strength"].rank(ascending=False, method="min"))
    s = float(rs["strength"].iloc[0]) if not rs.empty else 0.0
    g = _grade(s)
    rk = (int(ranked[(ranked["team"] == team) & (ranked["pos_group"] == pos)]["rk"].iloc[0])
          if not rs.empty else n)
    top = rs["top_player"].iloc[0] if (not rs.empty and "top_player" in rs.columns) else "—"
    color = _GRADE_BG.get(g, "#888")
    st.markdown(f"#### {pos} &nbsp;<span style='background:{color};color:white;"
                f"padding:1px 11px;border-radius:6px'>{g}</span>", unsafe_allow_html=True)
    a, b = st.columns(2)
    a.metric("NFL rank", f"#{rk} of {n}")
    b.metric("Anchor", top)
    if db.table_exists("free_agents"):
        pool = _free_agents()
        if "talent" in pool.columns:
            cands = pool[pool["pos_group"] == pos].nlargest(3, "talent")
            if not cands.empty:
                st.caption(f"Best available to upgrade {pos}:")
                show = cands[["player", "age", "madden_ovr", "est_apy"]].copy()
                for col in ("madden_ovr", "age"):
                    show[col] = show[col].round(0).astype("Int64")
                st.dataframe(show, hide_index=True, column_config={
                    "madden_ovr": st.column_config.NumberColumn("OVR"),
                    "est_apy": st.column_config.NumberColumn("$/yr", format="$%.1fM"),
                })


# --------------------------------------------------------------------------- #
# Super Bowl Maxer
# --------------------------------------------------------------------------- #
def maxer_tab() -> None:
    if not db.table_exists("roster_strength"):
        st.warning("No roster data loaded. Build it (after the cap ETL) with:\n\n"
                   "```\npython scripts/refresh_rosters.py\n```")
        return

    meta = _maxer_meta()
    st.subheader("How far is each team from a champion-caliber roster?")
    st.caption(
        f"Grades blend **preseason caliber** (Madden + production, age-adjusted) with "
        f"**live {meta.get('perf_season', meta['roster_season'])} performance** — "
        f"weighted more as games are played and projected to a full-season pace. "
        f"Players **out / on IR right now are set aside**, so each unit reflects who "
        f"actually suits up. Measured against a champion blueprint weighted by the "
        f"Boardroom's title-importance. "
        f"Roster: {meta['roster_season']} · grades: Madden {meta['madden_season']} · "
        f"**data as of {meta['data_as_of']}**"
    )

    n_added = meta.get("n_espn_added")
    if n_added:
        st.info(f"🔄 Rosters auto-filled with {int(n_added)} ESPN-listed players nflverse "
                "hadn't ingested yet (recent signings & rookies) — strength reflects "
                "current rosters.")
    elif db.table_exists("roster_crosscheck"):
        xc = db.read_table("roster_crosscheck")
        flagged = xc[xc["flagged"] == 1] if "flagged" in xc.columns else xc.iloc[0:0]
        if flagged.empty:
            st.success("Rosters match ESPN's live feed — no drift detected.", icon="✅")
        else:
            st.warning(f"{len(flagged)} team(s) differ from ESPN's live roster "
                       f"({', '.join(flagged['team'])}).", icon="⚠️")

    strength = _roster_strength()
    league = sb_maxer.league_table(strength)
    teams = sorted(strength["team"].unique())

    team = st.selectbox("Team", teams, key="mx_team",
                        index=teams.index("KC") if "KC" in teams else 0)
    rep = sb_maxer.team_report(team, strength)

    prev_season = int(meta["roster_season"]) - 1
    prev = _prior_rank(prev_season).get(team)
    cur = rep["rank"]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("SB outlook", f"{rep['readiness']:.1f}/100")
    rec = rep.get("season_record")
    c2.metric(f"{meta['roster_season']} record",
              f"{rec['wins']}–{rec['losses']}" if rec else "—",
              help="This season's results so far — blended into the outlook with a "
                   "weight that grows as more games are played.")
    c3.metric("Roster", f"{rep['roster_readiness']:.0f}")
    c4.metric("Organization", f"{rep['org_score']:.0f}")
    if prev:
        move = prev - cur                                # +ve = climbed the board
        delta = f"{move:+d} vs {prev_season} finish (#{prev})" if move \
            else f"same as {prev_season} finish (#{prev})"
        c5.metric(f"Predicted rank ({meta['roster_season']})",
                  f"#{cur} of {rep['n_teams']}",
                  delta=delta, delta_color=("normal" if move else "off"),
                  help=f"Where the Maxer projects {team} this year vs. where they "
                       f"finished the {prev_season} regular season (#{prev}).")
    else:
        c5.metric(f"Predicted rank ({meta['roster_season']})",
                  f"#{cur} of {rep['n_teams']}")
    st.caption(
        f"Biggest needs: **{', '.join(rep['top_needs']) or '—'}**  ·  "
        "Outlook = roster talent + organization pre-season, then **increasingly "
        "driven by this season's results** (up to 65% by ~week 10)  ·  "
        f"rank arrow = projection vs the {prev_season} final standings.")

    needs = rep["needs"]
    st.markdown("##### 🏟️ Your roster, on the field")
    st.caption("Your projected **starters** on the base most teams run — "
               "**11-personnel** offense (bottom) vs. a **nickel** defense (top). "
               "Boxes shade by unit grade (green strong → red weak); the **nickel "
               "back** is your 3rd corner and the **slot** your 3rd receiver. "
               "**Hover any box for the player.**")
    units = list(needs["pos_group"])            # weakest first
    picked = st.selectbox("🔍 Break down a unit (weakest first)", units,
                          key=f"mx_pick_{team}")
    roster = _player_talent() if db.table_exists("player_talent") else None
    fc = st.columns([1, 2, 1])
    with fc[1]:
        st.plotly_chart(_field_figure(team, strength, players=roster, highlight=picked),
                        use_container_width=True, key=f"field_{team}")

    left, right = st.columns([3, 2])
    with left:
        _position_detail(picked, team, strength)
    with right:
        st.caption("Report card — weakest first.")
        ranked = strength.assign(
            rk=strength.groupby("pos_group")["strength"].rank(ascending=False, method="min"))
        n_teams = strength["team"].nunique()
        team_rank = ranked[ranked["team"] == team].set_index("pos_group")["rk"]
        disp = needs[["pos_group", "gap", "priority"]].copy()
        disp.insert(1, "grade", needs["strength"].map(_grade))
        disp.insert(2, "rank", needs["pos_group"].map(
            lambda p: f"{int(team_rank.get(p, n_teams))} / {n_teams}"))
        st.dataframe(_style_grades(disp, ["grade"]), hide_index=True, height=360,
                     column_config={
                         "pos_group": st.column_config.TextColumn("pos"),
                         "gap": st.column_config.NumberColumn("gap", format="%.0f"),
                         "priority": st.column_config.NumberColumn("priority", format="%.0f"),
                     })

    st.divider()
    st.subheader(f"Free agents to fill {team}'s needs")
    if db.table_exists("free_agents"):
        recs = free_agents.recommend_for_team(team, strength, _free_agents())
        if recs.empty:
            st.caption("No clear free-agent upgrades at the top needs right now.")
        else:
            st.caption("Best available players (not on a current roster) at each "
                       "top need, ranked by age/trend-adjusted talent — with each "
                       "player's estimated cost (most recent contract APY).")
            st.dataframe(recs, hide_index=True, column_config={
                "madden_ovr": st.column_config.NumberColumn(format="%.0f"),
                "age": st.column_config.NumberColumn(format="%.1f"),
                "est_apy_$m": st.column_config.NumberColumn("est. $/yr (M)", format="$%.1f")})
    else:
        st.caption("Run `python scripts/refresh_rosters.py` to build the FA pool.")

    st.divider()
    st.subheader("League-wide SB outlook")
    lt = league[["rank", "team", "outlook", "roster_readiness", "org_score"]].copy()
    lt.insert(2, "grade", lt["outlook"].map(_grade))
    if {"wins", "losses", "games"}.issubset(league.columns) and int(league["games"].sum()) > 0:
        lt.insert(2, "rec", (league["wins"].astype(int).astype(str) + "–"
                             + league["losses"].astype(int).astype(str)))
    st.dataframe(_style_grades(lt, ["grade"]), hide_index=True, height=320,
                 column_config={
                     "rec": st.column_config.TextColumn(f"{config.CURRENT_SEASON}"),
                     "outlook": st.column_config.NumberColumn("outlook", format="%.0f"),
                     "roster_readiness": st.column_config.NumberColumn("roster", format="%.0f"),
                     "org_score": st.column_config.NumberColumn("org", format="%.0f"),
                 })
    st.caption("Refresh anytime with `python scripts/refresh_rosters.py --force` "
               "(scheduled daily to track signings, trades, and cuts).")


# --------------------------------------------------------------------------- #
# Value Board
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def _value_board() -> pd.DataFrame:
    """Value board — from the precomputed table if present, else built live."""
    if db.table_exists("value_board"):
        return db.read_table("value_board")
    return value_board.build_value_board(db.read_table("player_talent"))


_VALUE_COLS = {
    "pos_group": st.column_config.TextColumn("pos"),
    "madden_ovr": st.column_config.NumberColumn("OVR"),
    "apy": st.column_config.NumberColumn("$/yr", format="$%.1fM"),
    "value": st.column_config.TextColumn("value"),
}


def _fmt_value(df: pd.DataFrame) -> pd.DataFrame:
    out = df[["player", "team", "pos_group", "grade", "age", "madden_ovr",
              "apy", "value"]].copy()
    for col in ("madden_ovr", "age"):
        out[col] = out[col].round(0).astype("Int64")
    out["value"] = out["value"].map(lambda s: "★" * int(s) + "☆" * (5 - int(s)))
    return out


def value_tab() -> None:
    st.subheader("💎 Value Board — the best (and worst) contracts in football")
    st.caption("**Value index = caliber percentile − pay percentile**, within a "
               "position. +80 = a top-of-position talent on bottom-of-position "
               "money. Caliber = Madden rating; pay = contract APY (OverTheCap).")
    if not db.table_exists("player_talent"):
        st.info("Run `python scripts/refresh_rosters.py` to build the roster first.")
        return
    board = _value_board()

    c1, c2 = st.columns([1, 3])
    positions = ["All"] + sorted(board["pos_group"].unique())
    pos = c1.selectbox("Position", positions, key="vb_pos")
    n = c1.slider("How many", 10, 40, 25, key="vb_n")
    c1.caption("Sorted by value index; ★ = league-wide value tier.")

    best = value_board.best_values(board, pos_group=pos, n=n)
    c2.caption(f"**Best values{'' if pos == 'All' else ' — ' + pos}** — good player, cheap deal.")
    c2.dataframe(_style_grades(_fmt_value(best), ["grade"]), hide_index=True,
                 height=520, column_config=_VALUE_COLS)

    with st.expander("💸 Worst contracts — biggest overpays (well-paid, underdelivering)"):
        st.dataframe(_style_grades(_fmt_value(value_board.worst_contracts(board, n=15)),
                                   ["grade"]), hide_index=True, column_config=_VALUE_COLS)
    st.caption("Rebuilt on each `python scripts/refresh_rosters.py` (scheduled daily).")


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #
st.title("🏈 GridironIQ")
st.caption(THESIS)
boardroom, film_room, maxer, value = st.tabs([
    "📊 Boardroom — Cap Efficiency",
    "🎬 Film Room — Post-Game Breakdown",
    "🏆 Super Bowl Maxer",
    "💎 Value Board",
])
with boardroom:
    boardroom_tab()
with film_room:
    film_room_tab()
with maxer:
    maxer_tab()
with value:
    value_tab()
