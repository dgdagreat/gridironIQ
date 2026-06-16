"""
GridironIQ — Streamlit frontend.

Two clearly separated tabs:
  * Boardroom  — cap-efficiency analytics over the loaded SQLite model (live).
  * Film Room  — post-game breakdown via play-by-play metrics + Anthropic.

Run from the project root:
    streamlit run app/streamlit_app.py
"""

from __future__ import annotations

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
    team = c1.selectbox("Team", teams, index=teams.index("KC") if "KC" in teams else 0)
    season = c2.selectbox("Season", seasons, index=0)
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
# Film Room
# --------------------------------------------------------------------------- #
def film_room_tab() -> None:
    st.subheader("Post-game film breakdown")
    st.caption("Pulls nflfastR play-by-play, extracts tactical metrics, and asks "
               f"`{config.ANTHROPIC_MODEL}` to explain *why a team lost*.")

    st.info(
        "This tab pulls a full season of play-by-play (~40 MB) on first use and "
        "calls the Anthropic API, which requires `ANTHROPIC_API_KEY` in your `.env`.",
        icon="ℹ️",
    )

    season = st.number_input("Season", min_value=1999, max_value=config.END_SEASON,
                             value=config.END_SEASON, step=1)

    if not st.button("Load games", type="primary"):
        return

    try:
        from gridiron.filmroom import pbp_metrics
        with st.spinner(f"Loading {season} play-by-play…"):
            pbp = pbp_metrics.load_pbp(int(season))
            games = pbp_metrics.list_games(pbp)
    except Exception as exc:  # noqa: BLE001 - surface any ingest error in UI
        st.error(f"Could not load play-by-play: {exc}")
        return

    games["label"] = games.apply(
        lambda r: f"W{r.week}: {r.winner} def. {r.loser} "
                  f"({r.home_team} {r.home_score}–{r.away_score} {r.away_team})", axis=1)
    choice = st.selectbox("Game", games["label"])
    game_id = games.loc[games["label"] == choice, "game_id"].iloc[0]

    payload = pbp_metrics.build_breakdown_payload(pbp, game_id)
    with st.expander("Extracted metrics"):
        st.json(payload)

    if st.button("Generate film-room breakdown"):
        try:
            from gridiron.filmroom import breakdown
            with st.spinner("Writing the breakdown…"):
                report = breakdown.generate_breakdown(payload)
            st.markdown(report)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Breakdown failed: {exc}")


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

    strength = _roster_strength()
    league = sb_maxer.league_table(strength)
    teams = sorted(strength["team"].unique())

    team = st.selectbox("Team", teams,
                        index=teams.index("KC") if "KC" in teams else 0)
    rep = sb_maxer.team_report(team, strength)

    c1, c2, c3 = st.columns(3)
    c1.metric("Championship readiness", f"{rep['readiness']:.1f}/100")
    c2.metric("League rank", f"#{rep['rank']} of {rep['n_teams']}")
    c3.metric("Biggest needs", ", ".join(rep["top_needs"]) or "—")

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
    st.subheader("League-wide readiness")
    st.dataframe(league[["rank", "team", "readiness"]], hide_index=True, height=320)
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
