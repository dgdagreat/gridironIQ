"""
Free-agent recommender: who's available to fill a team's biggest needs.

Ties the Maxer together — it takes a team's ranked needs (from ``sb_maxer``) and,
for each, surfaces the best available free agents at that position, scored with
the same age/trend-adjusted talent model used for rostered players. The result is
a concrete shopping list: "you're thin at WR; here are the top available WRs."
"""

from __future__ import annotations

import pandas as pd

from gridiron.modeling import roster_strength, sb_maxer


def score_pool(fa_raw: pd.DataFrame) -> pd.DataFrame:
    """Apply the age/trend-adjusted talent score to the raw free-agent pool."""
    return roster_strength.player_talent_scores(fa_raw)


def recommend_for_team(team: str, strength: pd.DataFrame, pool: pd.DataFrame, *,
                       max_needs: int = 4, per_need: int = 5) -> pd.DataFrame:
    """Best available free agents for a team's top unmet needs.

    ``strength`` is the league roster-strength table; ``pool`` is the *scored*
    free-agent pool (has a ``talent`` column). Returns a tidy table:
    need, gap, player, last_team, age, madden_ovr, talent.
    """
    report = sb_maxer.team_report(team, strength)
    needs = report["needs"]
    unmet = needs[needs["gap"] > 0].head(max_needs)

    rows: list[dict] = []
    for need in unmet.itertuples(index=False):
        cands = (pool[pool["pos_group"] == need.pos_group]
                 .nlargest(per_need, "talent"))
        for c in cands.itertuples(index=False):
            rows.append({
                "need": need.pos_group,
                "gap": round(float(need.gap), 1),
                "player": c.player,
                "last_team": getattr(c, "last_team", None),
                "age": getattr(c, "age", None),
                "madden_ovr": getattr(c, "madden_ovr", None),
                "talent": round(float(c.talent), 3),
            })
    return pd.DataFrame(rows)


if __name__ == "__main__":  # demo (needs the refresh to have run)
    from gridiron import db
    pd.set_option("display.width", 170)
    strength = db.read_table("roster_strength")
    pool = db.read_table("free_agents")
    for team in ("KC", "CLE"):
        print(f"\n=== {team}: free-agent targets for top needs ===")
        print(recommend_for_team(team, strength, pool).to_string(index=False))
