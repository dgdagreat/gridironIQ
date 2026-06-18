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
ROSTER_WEIGHT = 0.55         # outlook = roster readiness (55%) + organization (45%)


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


def league_table(strength: pd.DataFrame) -> pd.DataFrame:
    """Per-team SB outlook (roster readiness blended with org) + rank.

    Columns: team, roster_readiness, org_score, outlook, rank.
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
    table["outlook"] = (ROSTER_WEIGHT * table["roster_readiness"]
                        + (1 - ROSTER_WEIGHT) * table["org_score"]).round(1)

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

    return {
        "team": team,
        "readiness": float(row["outlook"]),          # headline = blended outlook
        "roster_readiness": float(row["roster_readiness"]),
        "org_score": float(row["org_score"]),
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
