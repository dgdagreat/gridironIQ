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
    return sorted(df["season"].unique(), reverse=True), sorted(df["team"].unique())


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
        st.bar_chart(prem.set_index("pos_group")["premium"], height=380)
    with col2:
        st.dataframe(_verdict(), hide_index=True, height=380)

    st.divider()
    st.subheader("Team spending profile")
    st.caption(f"Positional cap allocation by season — history from "
               f"{config.START_SEASON}, projected out to {config.PROJECTION_SEASON} "
               "using cap already committed on signed multi-year deals.")
    seasons, teams = _seasons_teams()
    c1, c2 = st.columns(2)
    team = c1.selectbox("Team", teams, key="br_team",
                        index=teams.index("KC") if "KC" in teams else 0)
    _def_season = config.CURRENT_SEASON if config.CURRENT_SEASON in seasons else seasons[0]
    season = c2.selectbox("Season", seasons, index=seasons.index(_def_season),
                          key="br_season")
    if season > config.CURRENT_SEASON:
        st.info(f"⏳ **{season} is a projection** — only cap already tied up in "
                "signed multi-year contracts. Rosters aren't full this far out, so "
                "shares reflect *committed* money, not a complete team.")
    prof = _team_season(team, season)
    if prof.empty:
        st.info(f"No cap data for {team} in {season}.")
    else:
        left, right = st.columns([3, 2])
        left.bar_chart(prof.set_index("pos_group")["cap_pct_norm"], height=340)
        right.dataframe(prof, hide_index=True, height=340, column_config={
            "pos_group": st.column_config.TextColumn("pos"),
            "cap_pct": st.column_config.NumberColumn("cap %", format="percent"),
            "cap_pct_norm": st.column_config.NumberColumn("of team", format="percent"),
            "n_players": st.column_config.NumberColumn("players"),
        })

    st.divider()
    st.subheader("Winning roster archetypes (k-means on spending profiles)")
    k = st.slider("Number of archetypes", 3, 7, 5)
    success, profiles = _archetypes(k)
    st.caption("Each team-season clustered by its positional spending; archetypes "
               "labeled by their most *distinctive* investments and scored by title rate.")
    st.dataframe(success, hide_index=True)
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
#: drawn vertically (offense at the bottom, driving up). Each spot is a labeled
#: box colored by its position **group** grade; several boxes can share a group.
#: Coordinates are ``(label, group, x, y)`` with x = field width (0–53.3) and
#: y = field length (offense LOS ≈ 44).
_FORMATION: list[tuple[str, str, float, float]] = [
    # OFFENSE — shotgun 11 personnel, driving up
    ("WR", "WR", 3, 42.5), ("WR", "WR", 50, 42.5), ("WR", "WR", 10, 41),
    ("LT", "OL", 16, 44), ("LG", "OL", 21, 44), ("C", "OL", 26.5, 44),
    ("RG", "OL", 32, 44), ("RT", "OL", 37, 44),
    ("TE", "TE", 42, 44),
    ("QB", "QB", 25, 38), ("RB", "RB", 31, 38),
    # DEFENSE — nickel (4-2-5)
    ("DE", "EDGE", 15, 47), ("DT", "IDL", 22, 47), ("DT", "IDL", 31, 47),
    ("DE", "EDGE", 38, 47),
    ("LB", "LB", 21, 51), ("LB", "LB", 32, 51),
    ("CB", "CB", 3, 47), ("CB", "CB", 50, 47), ("NB", "CB", 11, 50),
    ("FS", "S", 18, 58), ("SS", "S", 35, 58),
]


def _field_figure(team: str, strength: pd.DataFrame, highlight: str | None = None):
    """Plotly formation view (vertical): the base personnel most teams run —
    11-personnel offense (bottom) vs. a nickel defense (top) — as labeled player
    boxes shaded by their position **group** grade (green strong → red weak).
    Boxes belonging to the ``highlight`` group get a bright gold ring.
    """
    import plotly.graph_objects as go
    rs = strength[strength["team"] == team].set_index("pos_group")
    ranked = strength.assign(
        rk=strength.groupby("pos_group")["strength"].rank(ascending=False, method="min"))
    tr = ranked[ranked["team"] == team].set_index("pos_group")["rk"]
    n = int(strength["team"].nunique())

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
    for label, grp, x, y in _FORMATION:
        if grp in rs.index:
            s = float(rs.at[grp, "strength"]); g = _grade(s); rk = int(tr.get(grp, n))
            top = rs.at[grp, "top_player"] if "top_player" in rs.columns else ""
            colors.append(_GRADE_BG[g])
            hovers.append(f"<b>{label}</b> · {grp} unit · grade {g}<br>"
                          f"#{rk} of {n} in the NFL · strength {s:.0f}/100<br>top: {top}")
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
        f"Current rosters scored on **production + external grade, adjusted for "
        f"age and recent production trend** (a static rating isn't gospel), measured "
        f"against a champion blueprint weighted by the Boardroom's title-importance. "
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

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("SB outlook", f"{rep['readiness']:.1f}/100")
    c2.metric("Roster", f"{rep['roster_readiness']:.0f}")
    c3.metric("Organization", f"{rep['org_score']:.0f}")
    c4.metric("League rank", f"#{rep['rank']} of {rep['n_teams']}")
    st.caption(
        f"Biggest needs: **{', '.join(rep['top_needs']) or '—'}**  ·  "
        "Outlook = 55% roster talent + 45% organization "
        "(coaching/GM/ownership proxy via recent franchise success).")

    needs = rep["needs"]
    st.markdown("##### 🏟️ Your roster, on the field")
    st.caption("The base most teams actually run — **11-personnel** offense (bottom) "
               "vs. a **nickel** defense (top). Each box is a player spot, shaded by "
               "its unit's grade (green strong → red weak); hover any box for detail.")
    units = list(needs["pos_group"])            # weakest first
    picked = st.selectbox("🔍 Break down a unit (weakest first)", units,
                          key=f"mx_pick_{team}")
    fc = st.columns([1, 2, 1])
    with fc[1]:
        st.plotly_chart(_field_figure(team, strength, highlight=picked),
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
    st.dataframe(_style_grades(lt, ["grade"]), hide_index=True, height=320,
                 column_config={
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
