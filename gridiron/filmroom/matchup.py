"""
Pre-game matchup preview payloads.

A game that hasn't kicked off has no play-by-play, so the preview is built from
each team's **form** (season-to-date or last-season EPA/efficiency profile) plus
their **roster-strength edges** (from the Super Bowl Maxer). The result is a
payload the breakdown layer turns into "keys to the game / who has the edge".
"""

from __future__ import annotations

import pandas as pd

from gridiron.filmroom import pbp_metrics
from gridiron.ingestion.reference import POSITION_GROUP_ORDER


def _strength_edges(home: str, away: str,
                    roster_strength: pd.DataFrame | None) -> list[dict] | None:
    """Per-position strength for both teams + the home-vs-away edge."""
    if roster_strength is None or roster_strength.empty:
        return None
    wide = roster_strength.pivot_table(index="team", columns="pos_group",
                                       values="strength")
    if home not in wide.index or away not in wide.index:
        return None
    rows = []
    for pos in POSITION_GROUP_ORDER:
        h = wide.at[home, pos] if pos in wide.columns else None
        a = wide.at[away, pos] if pos in wide.columns else None
        if pd.isna(h) or pd.isna(a):
            continue
        rows.append({"pos_group": pos, "home": round(float(h), 1),
                     "away": round(float(a), 1), "edge": round(float(h - a), 1)})
    return sorted(rows, key=lambda r: abs(r["edge"]), reverse=True)


def build_preview_payload(home: str, away: str, form_pbp: pd.DataFrame, *,
                          form_season: int, week: int | None = None,
                          roster_strength: pd.DataFrame | None = None) -> dict:
    """Assemble the pre-game preview payload (mode='pre').

    ``form_pbp`` is the play-by-play used for form — last completed season for an
    offseason matchup, or season-to-date once games have been played.
    """
    return {
        "mode": "pre",
        "matchup": f"{away} @ {home}",
        "week": week,
        "form_season": form_season,
        "home": home,
        "away": away,
        "home_form": pbp_metrics.team_form(form_pbp, home),
        "away_form": pbp_metrics.team_form(form_pbp, away),
        "roster_edges": _strength_edges(home, away, roster_strength),
    }
