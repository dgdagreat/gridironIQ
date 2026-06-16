"""
Central configuration for GridironIQ.

Holds filesystem paths, the salary-cap-era segmentation markers, the historical
league salary cap reference table, and remote data-source URLs. Everything that
is a *tunable* or a *segmentation marker* lives here; football reference data
(teams, positions, Super Bowl results) lives in ``gridiron.ingestion.reference``.
"""

from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------- #
# Filesystem layout
# --------------------------------------------------------------------------- #
PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]

DATA_DIR: Path = PROJECT_ROOT / "data"
RAW_DIR: Path = DATA_DIR / "raw"
PROCESSED_DIR: Path = DATA_DIR / "processed"
SQL_DIR: Path = PROJECT_ROOT / "sql"

#: SQLite database that backs the analytics + frontend layers.
DB_PATH: Path = DATA_DIR / "gridiron.db"
DB_URL: str = f"sqlite:///{DB_PATH}"

for _d in (DATA_DIR, RAW_DIR, PROCESSED_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------- #
# Analysis window
# --------------------------------------------------------------------------- #
#: The salary cap was introduced in 1994 -- the start of the modern "cap era".
START_SEASON: int = 1994
#: Last season with finalized results encoded in the reference data.
END_SEASON: int = 2024

# --------------------------------------------------------------------------- #
# Era segmentation markers
# --------------------------------------------------------------------------- #
# These are the structural breakpoints the thesis cares about: rule changes and
# CBAs that reshaped how positional value translates into wins. Each milestone
# is keyed by the first season it took effect.
ERA_MILESTONES: dict[int, str] = {
    1994: "Salary cap introduced",
    2004: "Defensive-contact rule emphasis (illegal contact / defensive holding)",
    2011: "2011 CBA (rookie wage scale, restructured cap mechanics)",
    2021: "17-game regular season",
}

#: Named eras as (start_season, end_season_inclusive, label). ``None`` end means
#: open-ended (present day). Used to bucket every season into one comparable bin.
ERAS: list[tuple[int, int | None, str]] = [
    (1994, 2003, "Early Cap Era"),
    (2004, 2010, "Post-2004 Rules"),
    (2011, 2020, "Post-2011 CBA"),
    (2021, None, "17-Game Era"),
]


def era_for_season(season: int) -> str:
    """Return the named era a given season belongs to."""
    for start, end, label in ERAS:
        if season >= start and (end is None or season <= end):
            return label
    return "Pre-Cap"


# --------------------------------------------------------------------------- #
# Historical league salary cap (per-team cap, in US dollars)
# --------------------------------------------------------------------------- #
# Public, well-documented figures. Used to convert raw positional cap dollars
# into "share of the cap" -- the unit the entire thesis is built on. 2010 was an
# uncapped year (no league cap), so spending shares are undefined that season.
#
# NOTE: rounded to published values; the ETL prefers each contract row's own
# cap-percentage field when available and falls back to this table otherwise.
LEAGUE_SALARY_CAP: dict[int, int | None] = {
    1994: 34_608_000,
    1995: 37_100_000,
    1996: 40_753_000,
    1997: 41_454_000,
    1998: 52_388_000,
    1999: 57_288_000,
    2000: 62_172_000,
    2001: 67_405_000,
    2002: 71_101_000,
    2003: 75_007_000,
    2004: 80_582_000,
    2005: 85_500_000,
    2006: 102_000_000,
    2007: 109_000_000,
    2008: 116_000_000,
    2009: 123_000_000,
    2010: None,  # uncapped year under the expiring CBA
    2011: 120_000_000,
    2012: 120_600_000,
    2013: 123_000_000,
    2014: 133_000_000,
    2015: 143_280_000,
    2016: 155_270_000,
    2017: 167_000_000,
    2018: 177_200_000,
    2019: 188_200_000,
    2020: 198_200_000,
    2021: 182_500_000,  # COVID-reduced cap
    2022: 208_200_000,
    2023: 224_800_000,
    2024: 255_400_000,
    2025: 279_200_000,
}

# --------------------------------------------------------------------------- #
# Remote data sources
# --------------------------------------------------------------------------- #
# nflverse publishes OverTheCap-sourced contract data as versioned release
# assets. The historical_contracts asset is player/contract level with a nested
# per-year cap breakdown -- the basis for positional spending shares.
NFLVERSE_RELEASE_BASE: str = (
    "https://github.com/nflverse/nflverse-data/releases/download"
)
CONTRACTS_PARQUET_URL: str = (
    f"{NFLVERSE_RELEASE_BASE}/contracts/historical_contracts.parquet"
)
CONTRACTS_CSV_URL: str = (
    f"{NFLVERSE_RELEASE_BASE}/contracts/historical_contracts.csv.gz"
)

# --------------------------------------------------------------------------- #
# Film Room (Anthropic) settings
# --------------------------------------------------------------------------- #
#: Model used to generate the natural-language film reports (pre- and post-game).
ANTHROPIC_MODEL: str = "claude-sonnet-4-6"
#: Headroom for adaptive thinking + the written report (well under the non-stream cap).
ANTHROPIC_MAX_TOKENS: int = 3000
