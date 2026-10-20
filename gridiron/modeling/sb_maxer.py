"""
Super Bowl Maxer: how far is a team's *current roster* from a champion's?

This is the Boardroom turned prescriptive. The Boardroom learned which positions
correlate with winning titles; the Maxer uses that as the **importance weights**
and a **blueprint** of how strong a contender needs to be at each position, then
measures each current roster's weighted gap from it.

    weights          ← Boardroom win-correlation (min-max scaled to [0.3, 1.0])
    blueprint[p]     = 50 + 25 · weight[p]   (strong where it matters, ~avg where it doesn't)
    roster_readiness = 100 · (1 − Σ weight·gap / Σ weight·blueprint)
    outlook          = 0.55 · roster_readiness + 0.45 · organization   # headline + rank
    needs            = positions ranked by weight·gap (biggest title-relevant holes)

A pure roster grade under-rates young, well-coached teams (a recent SB participant
can grade out as a mediocre depth chart), so the headline blends roster readiness
with an **organizational** score — a coaching/GM/ownership proxy from recent
franchise success (see :mod:`gridiron.modeling.organization`). The positional
*needs* stay roster-based, since that's the actionable part.
"""

from __future__ import annotations

import pandas as pd

from gridiron.modeling import cap_efficiency, organization

WEIGHT_FLOOR = 0.30          # no position is worth zero — you can't punt any of them
BLUEPRINT_BASE = 50.0        # contender baseline percentile at the least-critical spot
BLUEPRINT_SPAN = 25.0        # extra percentile demanded at the most-critical spot
ROSTER_WEIGHT = 0.55         # pre-season outlook = roster readiness (55%) + organization (45%)
FORM_WEIGHT_MAX = 0.40       # weight this season's results reach once it's complete (~17 games)


def position_weights() -> pd.Series:
    """Per-position importance weights derived from the Boardroom.

    Uses the correlation between a position's cap share and *winning* the Super
    Bowl, min-max scaled to ``[WEIGHT_FLOOR, 1.0]`` so the most title-correlated
    position weighs 1.0 and the least still carries a baseline.
    """
    corr = cap_efficiency.spending_success_corr().set_index("pos_group")["corr_win"]
    lo, hi = corr.min(), corr.max()
    scaled = WEIGHT_FLOOR + (corr - lo) / (hi - lo) * (1 - WEIGHT_FLOOR)
    return scaled.rename("weight")


def champion_blueprint(weights: pd.Series | None = None) -> pd.Series:
    """Target strength percentile a contender should hit at each position."""
    weights = position_weights() if weights is None else weights
    return (BLUEPRINT_BASE + BLUEPRINT_SPAN * weights).rename("blueprint")


def prior_season_rank(season: int) -> pd.DataFrame:
    """Where teams *finished* a completed regular season — the "going into this
    year" baseline the predicted outlook rank moves from.

    Ranks the teams by that season's regular-season record (win%, then point
    differential as tiebreak); rank 1 = best. Returns team, wins, losses,
    win_pct, point_diff, prev_rank — empty if ``season`` has no completed games.
    """
    from gridiron.ingestion import schedules
    from gridiron.ingestion.reference import CANONICAL_TEAMS, canonical_team

    sched = schedules.load_schedules()
    if "home_score" not in sched:
        return pd.DataFrame(columns=["team", "wins", "losses", "win_pct",
                                     "point_diff", "prev_rank"])
    gtype = sched["game_type"] if "game_type" in sched else "REG"
    g = sched[(sched["season"] == season) & sched["home_score"].notna()
              & (gtype == "REG")].copy()
    if g.empty:
        return pd.DataFrame(columns=["team", "wins", "losses", "win_pct",
                                     "point_diff", "prev_rank"])
    g["home"] = g["home_team"].map(canonical_team)
    g["away"] = g["away_team"].map(canonical_team)

    rec = {t: {"w": 0, "l": 0, "pf": 0, "pa": 0} for t in CANONICAL_TEAMS}
    for r in g.itertuples(index=False):
        for team, pts, opp in ((r.home, r.home_score, r.away_score),
                               (r.away, r.away_score, r.home_score)):
            if team not in rec:
                continue
            d = rec[team]
            d["pf"] += pts; d["pa"] += opp
            d["w"] += int(pts > opp); d["l"] += int(pts < opp)   # ties: neither

    rows = [{"team": t, "wins": d["w"], "losses": d["l"],
             "win_pct": d["w"] / (d["w"] + d["l"]) if (d["w"] + d["l"]) else 0.0,
             "point_diff": d["pf"] - d["pa"]} for t, d in rec.items()]
    df = pd.DataFrame(rows)
    df = df[(df["wins"] + df["losses"]) > 0]                      # teams that played
    df = df.sort_values(["win_pct", "point_diff"], ascending=False, ignore_index=True)
    df["prev_rank"] = df.index + 1
    return df


def current_form(season: int | None = None) -> pd.DataFrame:
    """This season's results so far — the in-season signal the outlook blends in.

    A 0–100 ``form_score`` from win percentage, plus ``games`` played (how much to
    trust it yet). Returns an empty frame before the season has any completed games.
    Columns: team, wins, losses, win_pct, point_diff, games, form_score.
    """
    from gridiron import config

    season = config.CURRENT_SEASON if season is None else season
    cur = prior_season_rank(season)
    if cur.empty:
        return cur
    cur = cur.assign(games=(cur["wins"] + cur["losses"]).astype(int),
                     form_score=(100.0 * cur["win_pct"]).round(1))
    return cur[["team", "wins", "losses", "win_pct", "point_diff",
                "games", "form_score"]]


def league_table(strength: pd.DataFrame) -> pd.DataFrame:
    """Per-team SB outlook + rank.

    Pre-season the outlook is roster readiness (55%) blended with organization
    (45%); once the season starts, this year's results are mixed in with a weight
    that grows with games played (so the rank fluctuates week to week while roster
    quality still anchors it early). Columns: team, roster_readiness, org_score,
    form_score, wins, losses, games, outlook, rank.
    """
    weights = position_weights()
    blueprint = champion_blueprint(weights)

    wide = strength.pivot_table(index="team", columns="pos_group",
                                values="strength", fill_value=0.0)
    gap = (blueprint - wide).clip(lower=0)               # only shortfalls count
    weighted_gap = gap.mul(weights, axis=1)
    denom = float((weights * blueprint).sum())
    roster = (100 * (1 - weighted_gap.sum(axis=1) / denom)).round(1)

    table = roster.rename("roster_readiness").reset_index()
    org = organization.franchise_strength()[["team", "org_score"]]
    table = table.merge(org, on="team", how="left")
    table["org_score"] = table["org_score"].fillna(50.0)
    table["base_outlook"] = (ROSTER_WEIGHT * table["roster_readiness"]
                             + (1 - ROSTER_WEIGHT) * table["org_score"]).round(1)

    # Mix in this season's results — weight ramps from ~0 at week 1 to
    # FORM_WEIGHT_MAX over a full 17-game season, so the roster/org projection
    # still anchors the outlook early while the rank moves as games are played.
    form = current_form()
    if not form.empty:
        table = table.merge(form[["team", "wins", "losses", "games", "form_score"]],
                            on="team", how="left")
        for col, dflt in (("wins", 0), ("losses", 0), ("games", 0)):
            table[col] = table[col].fillna(dflt).astype(int)
        table["form_score"] = table["form_score"].fillna(table["base_outlook"])
        w = (table["games"] / 17.0 * FORM_WEIGHT_MAX).clip(upper=FORM_WEIGHT_MAX)
        table["outlook"] = ((1 - w) * table["base_outlook"]
                            + w * table["form_score"]).round(1)
    else:
        for col in ("wins", "losses", "games"):
            table[col] = 0
        table["form_score"] = float("nan")
        table["outlook"] = table["base_outlook"]
    table = table.drop(columns="base_outlook")

    table = table.sort_values("outlook", ascending=False).reset_index(drop=True)
    table["rank"] = table.index + 1
    return table


def team_report(team: str, strength: pd.DataFrame) -> dict:
    """Full Maxer report for one team: score, rank, and ranked needs."""
    weights = position_weights()
    blueprint = champion_blueprint(weights)
    table = league_table(strength)

    if team not in set(table["team"]):
        raise KeyError(f"no roster strength loaded for team {team!r}")

    row = table.set_index("team").loc[team]
    ts = strength[strength["team"] == team].set_index("pos_group")["strength"]

    needs = pd.DataFrame({
        "pos_group": blueprint.index,
        "strength": [round(float(ts.get(p, 0.0)), 1) for p in blueprint.index],
        "blueprint": blueprint.round(1).values,
        "weight": weights.round(3).values,
    })
    needs["gap"] = (needs["blueprint"] - needs["strength"]).clip(lower=0).round(1)
    needs["priority"] = (needs["gap"] * needs["weight"]).round(2)
    needs = needs.sort_values("priority", ascending=False, ignore_index=True)

    games = int(row["games"]) if "games" in row.index else 0
    record = None
    if games > 0:
        record = {"wins": int(row["wins"]), "losses": int(row["losses"]),
                  "win_pct": round(int(row["wins"]) / games, 3)}
    return {
        "team": team,
        "readiness": float(row["outlook"]),          # headline = blended outlook
        "roster_readiness": float(row["roster_readiness"]),
        "org_score": float(row["org_score"]),
        "season_record": record,                     # this season so far (None pre-season)
        "games_played": games,
        "rank": int(row["rank"]),
        "n_teams": int(len(table)),
        "needs": needs,
        "top_needs": needs[needs["gap"] > 0]["pos_group"].head(3).tolist(),
    }


if __name__ == "__main__":  # demo (needs roster strength loaded; see refresh script)
    from gridiron import db
    pd.set_option("display.width", 160)
    strength = db.read_table("roster_strength")
    print(league_table(strength).to_string(index=False))
