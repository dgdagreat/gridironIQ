"""
Organizational strength — the coaching / GM / ownership factor.

Roster talent grades miss what actually got a team to the Super Bowl: coaching,
scheme, QB intangibles, front-office competence, and ownership stability. There's
no clean public feed for "how good is this coach/GM/owner," so we use the most
defensible objective proxy: **recent on-field success** (win rate, playoff runs,
and Super Bowl appearances), **recency-weighted** so the most recent season — and
a fresh SB run especially — carries the most signal. It captures the *net* effect
of the whole organization and updates itself every season.

Blended with roster readiness in :mod:`gridiron.modeling.sb_maxer` so a proven
team the talent grades under-rate (e.g. a young, well-coached SB participant)
isn't buried beneath teams that merely look good on a Madden depth chart.
"""

from __future__ import annotations

import pandas as pd

from gridiron.ingestion import schedules
from gridiron.ingestion.reference import CANONICAL_TEAMS, canonical_team

#: Recency weights — most recent season dominates (a current SB run matters most).
RECENCY_WEIGHTS: dict[int, float] = {2025: 0.50, 2024: 0.30, 2023: 0.20}

# Per-season credit on top of regular-season win rate.
PLAYOFF_BONUS = 0.15
SB_APP_BONUS = 0.25
SB_WIN_BONUS = 0.20


def franchise_strength(weights: dict[int, float] | None = None) -> pd.DataFrame:
    """Per-team organizational score (0–100), recency-weighted.

    Columns: team, win_pct (3yr), playoff_seasons, sb_apps, sb_wins, org_score.
    """
    weights = weights or RECENCY_WEIGHTS
    seasons = tuple(weights)

    sched = schedules.load_schedules()
    g = sched[sched["season"].isin(seasons) & sched["home_score"].notna()].copy()
    g["home"] = g["home_team"].map(canonical_team)
    g["away"] = g["away_team"].map(canonical_team)

    rec = {t: {s: {"w": 0, "gp": 0, "po": False, "sb": 0, "sbw": 0} for s in seasons}
           for t in CANONICAL_TEAMS}
    for r in g.itertuples(index=False):
        if r.home not in rec or r.away not in rec or r.season not in seasons:
            continue
        gt = getattr(r, "game_type", "REG")
        is_reg = gt == "REG"
        for team, pts, opp in ((r.home, r.home_score, r.away_score),
                               (r.away, r.away_score, r.home_score)):
            d = rec[team][r.season]
            if is_reg:
                d["gp"] += 1
                d["w"] += int(pts > opp)
            else:
                d["po"] = True
                if gt == "SB":
                    d["sb"] += 1
                    d["sbw"] += int(pts > opp)

    rows = []
    for t in CANONICAL_TEAMS:
        org_raw = tot_w = tot_gp = po_seasons = sb_apps = sb_wins = 0
        for s in seasons:
            d = rec[t][s]
            wp = d["w"] / d["gp"] if d["gp"] else 0.0
            season_score = (wp + PLAYOFF_BONUS * d["po"]
                            + SB_APP_BONUS * (d["sb"] > 0) + SB_WIN_BONUS * (d["sbw"] > 0))
            org_raw += weights[s] * season_score
            tot_w += d["w"]; tot_gp += d["gp"]; po_seasons += int(d["po"])
            sb_apps += d["sb"]; sb_wins += d["sbw"]
        rows.append({
            "team": t,
            "win_pct": round(tot_w / tot_gp, 3) if tot_gp else 0.0,
            "playoff_seasons": po_seasons, "sb_apps": sb_apps, "sb_wins": sb_wins,
            "raw": org_raw,
        })
    df = pd.DataFrame(rows)
    df["org_score"] = (df["raw"].rank(pct=True) * 100).round(1)
    return df.sort_values("org_score", ascending=False, ignore_index=True)


if __name__ == "__main__":
    pd.set_option("display.width", 160)
    print(franchise_strength().to_string(index=False))
