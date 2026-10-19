"""Export analysis-ready CSVs for the GridironIQ Tableau dashboard.

Reads the dbt marts (and the published EPA / value-board tables) from the local
DuckDB warehouse and writes tidy, Tableau-friendly CSVs into ``tableau/data/``.
Run after ``warehouse/build.py`` (or a Dagster materialize) has built the marts:

    .venv/bin/python tableau/export_data.py

Each file is a small aggregate — the shapes Tableau wants, not the raw data.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "warehouse.duckdb"
OUT = Path(__file__).resolve().parent / "data"
OUT.mkdir(parents=True, exist_ok=True)

POS_LABEL = {
    "QB": "Quarterback", "RB": "Running Back", "WR": "Wide Receiver",
    "TE": "Tight End", "OL": "Offensive Line", "IDL": "Interior D-Line",
    "EDGE": "Edge Rusher", "LB": "Linebacker", "CB": "Cornerback",
    "S": "Safety", "SPEC": "Special Teams",
}
PCT_COLS = ["pct_qb", "pct_rb", "pct_wr", "pct_te", "pct_ol", "pct_idl",
            "pct_edge", "pct_lb", "pct_cb", "pct_s", "pct_spec"]


def _write(df: pd.DataFrame, name: str) -> None:
    path = OUT / name
    df.to_csv(path, index=False)
    print(f"  {name:<36} {len(df):>6} rows")


def main() -> None:
    if not DB.exists():
        raise SystemExit(f"warehouse not found: {DB} — run warehouse/build.py first")
    con = duckdb.connect(str(DB), read_only=True)
    print(f"exporting from {DB} -> {OUT}")

    # 1) Champion premium by position — the signature finding.
    champ = con.execute("""
        SELECT pos_group, league_avg_pct, finalist_avg_pct, champion_avg_pct,
               champion_premium
        FROM main.mart_position_success
        ORDER BY champion_premium DESC
    """).fetchdf()
    champ.insert(0, "position", champ["pos_group"].map(POS_LABEL).fillna(champ["pos_group"]))
    champ["spend_tilt"] = champ["champion_premium"].apply(
        lambda v: "Champions pay up" if v > 0 else "Value position")
    _write(champ, "champion_premium_by_position.csv")

    # 2) Positional cap share by era.
    era = con.execute("""
        SELECT era, pos_group, n_team_seasons, avg_cap_pct
        FROM main.mart_positional_era_avg
        ORDER BY era, pos_group
    """).fetchdf()
    era.insert(2, "position", era["pos_group"].map(POS_LABEL).fillna(era["pos_group"]))
    _write(era, "positional_spending_by_era.csv")

    # 3) Team-season positional spend, melted long (one row per team-season-position).
    wide = con.execute(f"""
        SELECT season, team, era, sb_appearance, sb_win, {', '.join(PCT_COLS)}
        FROM main.fct_team_season
        ORDER BY season, team
    """).fetchdf()
    long = wide.melt(
        id_vars=["season", "team", "era", "sb_appearance", "sb_win"],
        value_vars=PCT_COLS, var_name="pos_group", value_name="cap_pct")
    long["pos_group"] = long["pos_group"].str.replace("pct_", "", regex=False).str.upper()
    long.insert(3, "position", long["pos_group"].map(POS_LABEL).fillna(long["pos_group"]))
    long["outcome"] = long["sb_win"].map({1: "Won SB"}).fillna(
        long["sb_appearance"].map({1: "SB appearance"})).fillna("Did not reach SB")
    _write(long, "team_season_positional_long.csv")

    # 4) On-field efficiency — team EPA, latest season on the warehouse.
    epa = con.execute("""
        SELECT season, team, off_epa_play, def_epa_play_allowed, net_epa_play,
               off_success_rate, off_explosive_rate, def_pressure_rate
        FROM raw.pbp_team_season_epa
        ORDER BY net_epa_play DESC
    """).fetchdf()
    _write(epa, "team_epa.csv")

    # 5) Value board — most cap-efficient players.
    vb = con.execute("""
        SELECT player, team, pos_group, age, grade, caliber_pct, pay_pct,
               apy, value_index
        FROM raw.value_board
        ORDER BY value_index DESC
    """).fetchdf()
    vb.insert(3, "position", vb["pos_group"].map(POS_LABEL).fillna(vb["pos_group"]))
    _write(vb, "value_board.csv")

    con.close()
    print("done.")


if __name__ == "__main__":
    main()
