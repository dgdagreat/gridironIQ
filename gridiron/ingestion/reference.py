"""
Football reference data used to normalize and label raw cap data.

  * ``TEAM_ALIASES``   -- collapse historical/relocated abbreviations onto a
                          single canonical franchise code so a franchise's
                          spending and championships line up across moves.
  * ``POSITION_GROUPS``-- map granular OverTheCap/roster position labels onto
                          the ~11 spending buckets the thesis reasons about.
  * ``SUPER_BOWL_RESULTS`` -- season-by-season SB participants and winners, the
                          target signal positional spending is correlated with.
"""

from __future__ import annotations

import pandas as pd

# --------------------------------------------------------------------------- #
# Canonical franchise codes (nflverse-style, current-day abbreviations)
# --------------------------------------------------------------------------- #
CANONICAL_TEAMS: set[str] = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN",
    "DET", "GB", "HOU", "IND", "JAX", "KC", "LV", "LAC", "LAR", "MIA",
    "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SF", "SEA", "TB",
    "TEN", "WAS",
}

#: Map every alternate/relocated/old abbreviation onto its canonical franchise.
TEAM_ALIASES: dict[str, str] = {
    # relocations
    "OAK": "LV", "LVR": "LV",
    "SD": "LAC", "SDG": "LAC",
    "STL": "LAR", "RAM": "LAR", "LA": "LAR",
    "OTI": "TEN", "HOI": "TEN",          # Houston/Tennessee Oilers -> Titans
    # spelling / 3-letter variants seen across sources
    "GNB": "GB", "KAN": "KC", "NWE": "NE", "NOR": "NO", "SFO": "SF",
    "TAM": "TB", "JAC": "JAX", "NWE ": "NE",
    "WFT": "WAS", "WSH": "WAS",          # Washington Football Team / variants
    "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU",
}


#: Full team nicknames -> canonical code. The nflverse contracts source stores
#: the per-season team inside its nested detail as a nickname ("Bengals"), and
#: historical names ("Oilers", "Redskins") must collapse onto the modern code.
NICKNAME_TO_CODE: dict[str, str] = {
    "cardinals": "ARI", "falcons": "ATL", "ravens": "BAL", "bills": "BUF",
    "panthers": "CAR", "bears": "CHI", "bengals": "CIN", "browns": "CLE",
    "cowboys": "DAL", "broncos": "DEN", "lions": "DET", "packers": "GB",
    "texans": "HOU", "colts": "IND", "jaguars": "JAX", "chiefs": "KC",
    "raiders": "LV", "chargers": "LAC", "rams": "LAR", "dolphins": "MIA",
    "vikings": "MIN", "patriots": "NE", "saints": "NO", "giants": "NYG",
    "jets": "NYJ", "eagles": "PHI", "steelers": "PIT", "49ers": "SF",
    "niners": "SF", "seahawks": "SEA", "buccaneers": "TB", "titans": "TEN",
    "oilers": "TEN", "commanders": "WAS", "redskins": "WAS",
    "football team": "WAS",
}


def canonical_team(code: str | float | None) -> str | None:
    """Normalize a raw team value (abbreviation *or* nickname) to a franchise code.

    Returns ``None`` for blanks and unresolvable multi-team career strings
    (e.g. ``"ARI/ATL"``) so they drop out of per-season aggregation.
    """
    if code is None or (isinstance(code, float) and pd.isna(code)):
        return None
    raw = str(code).strip()
    if not raw:
        return None

    upper = raw.upper()
    if upper in CANONICAL_TEAMS:
        return upper
    if upper in TEAM_ALIASES:
        return TEAM_ALIASES[upper]

    lower = raw.lower()
    if lower in NICKNAME_TO_CODE:
        return NICKNAME_TO_CODE[lower]
    # tolerate "Washington Football Team", "LA Rams", etc.
    for nickname, team in NICKNAME_TO_CODE.items():
        if nickname in lower:
            return team
    return None


# --------------------------------------------------------------------------- #
# Position groups
# --------------------------------------------------------------------------- #
# Buckets follow OverTheCap's spending taxonomy so results are comparable to
# published positional-spending tables. Defense is split into IDL/EDGE/LB and
# CB/S because the thesis (pass rush vs. coverage value) needs that resolution.
POSITION_GROUPS: dict[str, str] = {
    # Quarterback
    "QB": "QB",
    # Running back / fullback
    "RB": "RB", "HB": "RB", "FB": "RB",
    # Wide receiver
    "WR": "WR",
    # Tight end
    "TE": "TE",
    # Offensive line
    "OL": "OL", "T": "OL", "OT": "OL", "LT": "OL", "RT": "OL",
    "G": "OL", "OG": "OL", "LG": "OL", "RG": "OL", "C": "OL", "IOL": "OL",
    # Interior defensive line
    "IDL": "IDL", "DT": "IDL", "NT": "IDL", "DL": "IDL", "DI": "IDL",
    # Edge rushers
    "EDGE": "EDGE", "DE": "EDGE", "OLB": "EDGE", "ED": "EDGE",
    # Off-ball linebackers
    "LB": "LB", "ILB": "LB", "MLB": "LB",
    # Secondary
    "CB": "CB", "DB": "CB",
    "S": "S", "SAF": "S", "FS": "S", "SS": "S",
    # Specialists
    "K": "SPEC", "P": "SPEC", "LS": "SPEC", "PK": "SPEC",
}

#: Canonical ordering for display / model feature columns.
POSITION_GROUP_ORDER: list[str] = [
    "QB", "RB", "WR", "TE", "OL", "IDL", "EDGE", "LB", "CB", "S", "SPEC",
]


def classify_position(pos: str | float | None) -> str:
    """Map a raw position label onto a spending bucket (``UNK`` if unknown)."""
    if pos is None or (isinstance(pos, float) and pd.isna(pos)):
        return "UNK"
    return POSITION_GROUPS.get(str(pos).strip().upper(), "UNK")


# --------------------------------------------------------------------------- #
# Super Bowl results, by *season* (not the calendar year the game was played).
# Codes are canonical franchise codes so relocations stay on one timeline.
# Encoded through the 2024 season (Super Bowl LIX). Append future results here.
# --------------------------------------------------------------------------- #
SUPER_BOWL_RESULTS: list[dict[str, object]] = [
    {"season": 1994, "winner": "SF",  "loser": "LAC"},
    {"season": 1995, "winner": "DAL", "loser": "PIT"},
    {"season": 1996, "winner": "GB",  "loser": "NE"},
    {"season": 1997, "winner": "DEN", "loser": "GB"},
    {"season": 1998, "winner": "DEN", "loser": "ATL"},
    {"season": 1999, "winner": "LAR", "loser": "TEN"},
    {"season": 2000, "winner": "BAL", "loser": "NYG"},
    {"season": 2001, "winner": "NE",  "loser": "LAR"},
    {"season": 2002, "winner": "TB",  "loser": "LV"},
    {"season": 2003, "winner": "NE",  "loser": "CAR"},
    {"season": 2004, "winner": "NE",  "loser": "PHI"},
    {"season": 2005, "winner": "PIT", "loser": "SEA"},
    {"season": 2006, "winner": "IND", "loser": "CHI"},
    {"season": 2007, "winner": "NYG", "loser": "NE"},
    {"season": 2008, "winner": "PIT", "loser": "ARI"},
    {"season": 2009, "winner": "NO",  "loser": "IND"},
    {"season": 2010, "winner": "GB",  "loser": "PIT"},
    {"season": 2011, "winner": "NYG", "loser": "NE"},
    {"season": 2012, "winner": "BAL", "loser": "SF"},
    {"season": 2013, "winner": "SEA", "loser": "DEN"},
    {"season": 2014, "winner": "NE",  "loser": "SEA"},
    {"season": 2015, "winner": "DEN", "loser": "CAR"},
    {"season": 2016, "winner": "NE",  "loser": "ATL"},
    {"season": 2017, "winner": "PHI", "loser": "NE"},
    {"season": 2018, "winner": "NE",  "loser": "LAR"},
    {"season": 2019, "winner": "KC",  "loser": "SF"},
    {"season": 2020, "winner": "TB",  "loser": "KC"},
    {"season": 2021, "winner": "LAR", "loser": "CIN"},
    {"season": 2022, "winner": "KC",  "loser": "PHI"},
    {"season": 2023, "winner": "KC",  "loser": "SF"},
    {"season": 2024, "winner": "PHI", "loser": "KC"},
]


def super_bowl_frame() -> pd.DataFrame:
    """Return a tidy (team, season, sb_appearance, sb_win) outcomes table."""
    rows: list[dict[str, object]] = []
    for r in SUPER_BOWL_RESULTS:
        rows.append({"season": r["season"], "team": r["winner"],
                     "sb_appearance": 1, "sb_win": 1})
        rows.append({"season": r["season"], "team": r["loser"],
                     "sb_appearance": 1, "sb_win": 0})
    return pd.DataFrame(rows)
