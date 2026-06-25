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
from gridiron.modeling import cap_efficiency, clustering, free_agents, sb_maxer

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
    seasons, teams = _seasons_teams()
    c1, c2 = st.columns(2)
    team = c1.selectbox("Team", teams, key="br_team",
                        index=teams.index("KC") if "KC" in teams else 0)
    season = c2.selectbox("Season", seasons, index=0, key="br_season")
    prof = _team_season(team, season)
    if prof.empty:
        st.info(f"No cap data for {team} in {season}.")
    else:
        left, right = st.columns([3, 2])
        left.bar_chart(prof.set_index("pos_group")["cap_pct_norm"], height=340)
        right.dataframe(prof, hide_index=True, height=340)

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
            st.caption("Biggest roster-strength edges (home − away, percentile):")
            st.dataframe(pd.DataFrame(payload["roster_edges"]).head(6), hide_index=True)
        with st.expander("Team form + edges"):
            st.json(payload)
        if st.button("Generate matchup preview", type="primary"):
            _run_report(breakdown, payload)


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
    left, right = st.columns([3, 2])
    with left:
        st.caption("Positional strength (percentile vs. league) — bar — against "
                   "the champion blueprint (target).")
        chart = needs.set_index("pos_group")[["strength", "blueprint"]]
        st.bar_chart(chart, height=360)
    with right:
        st.caption("Needs, ranked by title-weighted gap.")
        st.dataframe(needs[["pos_group", "strength", "blueprint", "gap", "priority"]],
                     hide_index=True, height=360)

    st.divider()
    st.subheader(f"Free agents to fill {team}'s needs")
    if db.table_exists("free_agents"):
        recs = free_agents.recommend_for_team(team, strength, _free_agents())
        if recs.empty:
            st.caption("No clear free-agent upgrades at the top needs right now.")
        else:
            st.caption("Best available players (not on a current roster) at each "
                       "top need, ranked by the same age/trend-adjusted talent.")
            st.dataframe(recs, hide_index=True,
                         column_config={"madden_ovr": st.column_config.NumberColumn(format="%.0f"),
                                        "age": st.column_config.NumberColumn(format="%.1f")})
    else:
        st.caption("Run `python scripts/refresh_rosters.py` to build the FA pool.")

    st.divider()
    st.subheader("League-wide SB outlook")
    st.dataframe(league[["rank", "team", "outlook", "roster_readiness", "org_score"]],
                 hide_index=True, height=320)
    st.caption("Refresh anytime with `python scripts/refresh_rosters.py --force` "
               "(scheduled daily to track signings, trades, and cuts).")


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #
st.title("🏈 GridironIQ")
st.caption(THESIS)
boardroom, film_room, maxer = st.tabs([
    "📊 Boardroom — Cap Efficiency",
    "🎬 Film Room — Post-Game Breakdown",
    "🏆 Super Bowl Maxer",
])
with boardroom:
    boardroom_tab()
with film_room:
    film_room_tab()
with maxer:
    maxer_tab()
