"""
MVP / award "buzz" — a small, transparent reputation signal from betting markets.

Betting odds aggregate exactly the media + expert sentiment that "MVP talk" means,
so we use the **implied win probability** for the major individual awards (MVP,
OPOY, DPOY) as a bounded nudge to a player's grade.

This is deliberately a **manual snapshot** — there is no clean auto-updating odds
feed — so it carries an :data:`AS_OF` date and should be re-pulled when the award
races move. It is applied with a small weight on purpose (see
``roster_strength.BUZZ_WEIGHT``): hype *informs* the ranking, it never overturns
the data-driven grade. Matching is by (name, team) so same-named players (e.g. the
QB Josh Allen vs. the edge Josh Allen) don't cross-contaminate.
"""

from __future__ import annotations

import re

#: Snapshot date of the odds below — re-pull when the award races move.
AS_OF = "2026-10-22"  # Week 7, 2026 season

#: (player, team, award, implied_win_prob) from current sportsbook/market odds.
AWARD_BUZZ: list[tuple[str, str, str, float]] = [
    # MVP
    ("Josh Allen",         "BUF", "MVP",  0.31),
    ("Brock Purdy",        "SF",  "MVP",  0.27),
    ("Patrick Mahomes",    "KC",  "MVP",  0.10),
    ("Joe Burrow",         "CIN", "MVP",  0.085),
    ("Drake Maye",         "NE",  "MVP",  0.083),
    # Offensive Player of the Year
    ("Kenneth Walker III", "KC",  "OPOY", 0.33),
    ("Jahmyr Gibbs",       "DET", "OPOY", 0.29),
    # Defensive Player of the Year
    ("Will Anderson Jr.",  "HOU", "DPOY", 0.38),
    ("Fred Warner",        "SF",  "DPOY", 0.11),
    ("Dallas Turner",      "MIN", "DPOY", 0.09),
    ("Greg Rousseau",      "BUF", "DPOY", 0.08),
    ("Aidan Hutchinson",   "DET", "DPOY", 0.063),
]

_SUFFIX = re.compile(r"\s+(jr|sr|ii|iii|iv|v)\.?$")


def _norm(name: object) -> str:
    """Lowercase, drop periods and a trailing Jr./III/etc. so names match cleanly."""
    s = str(name).lower().replace(".", "").strip()
    return _SUFFIX.sub("", s).strip()


def buzz_scores() -> dict[tuple[str, str], float]:
    """``{(normalized_name, team) -> buzz 0..1}`` — the highest implied win
    probability if a player carries buzz in more than one award race."""
    out: dict[tuple[str, str], float] = {}
    for player, team, _award, p in AWARD_BUZZ:
        key = (_norm(player), team)
        out[key] = max(out.get(key, 0.0), float(p))
    return out


def player_buzz(names, teams) -> list[float]:
    """Buzz for aligned sequences of player names + teams (0.0 where none)."""
    b = buzz_scores()
    return [b.get((_norm(n), t), 0.0) for n, t in zip(names, teams)]
