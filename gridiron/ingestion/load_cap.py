"""
Cap ETL orchestration: contracts -> tidy tables -> SQLite + processed extracts.

``run_etl()`` is the single entry point the CLI script and tests call. It is
idempotent: the schema is dropped/recreated each run, so re-running fully
refreshes the Boardroom data layer.
"""

from __future__ import annotations

import logging

import pandas as pd

from gridiron import config, db
from gridiron.ingestion import cap_data
from gridiron.ingestion.reference import SUPER_BOWL_RESULTS, super_bowl_frame

log = logging.getLogger(__name__)

# Column contracts that must match sql/01_schema.sql exactly.
_PYC_COLS = ["otc_id", "player", "position", "season", "team",
             "cap_number", "cap_percent"]


def build_reference_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Construct league_cap, super_bowls, and team_outcomes from static refs."""
    league = pd.DataFrame(
        {"season": list(config.LEAGUE_SALARY_CAP.keys()),
         "league_cap": list(config.LEAGUE_SALARY_CAP.values())}
    )
    league["era"] = league["season"].map(config.era_for_season)
    league["milestone"] = league["season"].map(config.ERA_MILESTONES)

    super_bowls = pd.DataFrame(SUPER_BOWL_RESULTS)[["season", "winner", "loser"]]
    outcomes = super_bowl_frame()
    return league, super_bowls, outcomes


def run_etl(force_download: bool = False, save_processed: bool = True) -> dict:
    """Run the full cap ETL and return a summary dict.

    Stages: download -> explode -> aggregate -> pivot -> load (schema, tables,
    views) -> optional processed extracts.
    """
    log.info("== GridironIQ cap ETL ==")

    contracts = cap_data.load_raw_contracts(force_download=force_download)
    log.info("Loaded %d raw contract rows", len(contracts))

    player_year = cap_data.build_player_year_caps(contracts)
    log.info("Exploded to %d player-season cap rows", len(player_year))

    spending = cap_data.build_positional_spending(player_year)
    features = cap_data.build_spending_features(spending)
    league, super_bowls, outcomes = build_reference_tables()

    # ---- load into SQLite: schema -> tables -> views ----
    db.run_sql_script(config.SQL_DIR / "01_schema.sql")
    db.write_table(league, "league_cap", if_exists="append")
    db.write_table(super_bowls, "super_bowls", if_exists="append")
    db.write_table(outcomes, "team_outcomes", if_exists="append")
    db.write_table(player_year[_PYC_COLS], "player_year_caps", if_exists="append")
    db.write_table(spending, "positional_spending", if_exists="append")
    db.write_table(features, "spending_features", if_exists="append")
    db.run_sql_script(config.SQL_DIR / "02_views.sql")
    log.info("Loaded all tables + views into %s", config.DB_PATH)

    if save_processed:
        _save_processed(player_year, spending, features)

    seasons = spending["season"]
    summary = {
        "raw_contracts": len(contracts),
        "player_year_caps": len(player_year),
        "positional_rows": len(spending),
        "team_seasons": len(features),
        "season_min": int(seasons.min()),
        "season_max": int(seasons.max()),
        "teams": spending["team"].nunique(),
        "db_path": str(config.DB_PATH),
    }
    log.info("ETL complete: %s", summary)
    return summary


def _save_processed(player_year, spending, features) -> None:
    """Write flat extracts for the modeling layer / quick inspection."""
    player_year.to_parquet(config.PROCESSED_DIR / "player_year_caps.parquet")
    spending.to_csv(config.PROCESSED_DIR / "positional_spending.csv", index=False)
    features.to_csv(config.PROCESSED_DIR / "spending_features.csv", index=False)
    log.info("Wrote processed extracts to %s", config.PROCESSED_DIR)
