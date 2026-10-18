"""Dagster orchestration for GridironIQ.

Unifies the whole platform into one asset graph with lineage + a daily schedule,
replacing the launchd cron:

    boardroom_cap_etl ┐
                      ├─► raw.<tables> ─► [dbt: staging ─► marts] ─► sb_win_model
    maxer_rosters ────┘

Python ingestion assets and dbt model assets live in the SAME graph: the
`raw_warehouse` multi-asset produces one asset per raw table, keyed to match the
dbt sources, so every dbt model depends on the landing step.

Run the UI:   dagster dev -f orchestration/definitions.py
"""
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dagster import (
    AssetExecutionContext,
    AssetKey,
    AssetSelection,
    AssetSpec,
    Definitions,
    MaterializeResult,
    MetadataValue,
    ScheduleDefinition,
    asset,
    define_asset_job,
    multi_asset,
)
from dagster_dbt import (
    DagsterDbtTranslator,
    DbtCliResource,
    DbtProject,
    dbt_assets,
)

REPO = Path(__file__).resolve().parents[1]
WAREHOUSE_DIR = REPO / "warehouse"
DUCKDB_PATH = REPO / "data" / "warehouse.duckdb"

# Raw tables declared as dbt sources in warehouse/models/staging/_sources.yml.
# The landing asset produces one Dagster asset per table, keyed ["raw", <table>]
# to line up with the dbt source keys below.
RAW_SOURCE_TABLES = [
    "positional_spending",
    "spending_features",
    "team_outcomes",
    "league_cap",
    "super_bowls",
    "player_year_caps",
    "roster_strength",
    "value_board",
]

# dbt reads its profile from warehouse/profiles.yml.
os.environ.setdefault("DBT_PROFILES_DIR", str(WAREHOUSE_DIR))

dbt_project = DbtProject(project_dir=WAREHOUSE_DIR)
dbt_project.prepare_if_dev()  # runs `dbt parse` under `dagster dev`


#: pyspark 3.5 on Java 17+ needs these module opens; harmless on 11, and the
#: Databricks runtime sets its own, so this only matters for the local JVM.
_JAVA_OPENS = " ".join(
    f"--add-opens=java.base/{m}=ALL-UNNAMED" for m in (
        "java.lang", "java.lang.invoke", "java.io", "java.net", "java.nio",
        "java.util", "java.util.concurrent", "sun.nio.ch", "sun.security.action"))


def _run(cmd: list[str], context: AssetExecutionContext,
         env: dict | None = None) -> None:
    """Run a subprocess, streaming output into the Dagster logs."""
    context.log.info("$ " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                          check=False, env=env)
    if proc.stdout:
        context.log.info(proc.stdout[-4000:])
    if proc.returncode != 0:
        context.log.error(proc.stderr[-4000:])
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}")


# --------------------------------------------------------------------------
# Ingestion assets (wrap the existing scripts — they own the OTC/nflverse traps)
# --------------------------------------------------------------------------
@asset(group_name="ingestion", compute_kind="python")
def boardroom_cap_etl(context: AssetExecutionContext) -> MaterializeResult:
    """Cap ETL -> SQLite Boardroom tables (positional_spending, outcomes, ...)."""
    _run([sys.executable, str(REPO / "scripts" / "run_cap_etl.py")], context)
    return MaterializeResult(metadata={"script": "scripts/run_cap_etl.py"})


@asset(group_name="ingestion", compute_kind="python")
def maxer_rosters(context: AssetExecutionContext) -> MaterializeResult:
    """Roster refresh -> roster_strength, value_board, free_agents (Maxer)."""
    _run([sys.executable, str(REPO / "scripts" / "refresh_rosters.py")], context)
    return MaterializeResult(metadata={"script": "scripts/refresh_rosters.py"})


# --------------------------------------------------------------------------
# Warehouse landing (ingestion -> warehouse boundary). One asset per raw table.
# --------------------------------------------------------------------------
@multi_asset(
    specs=[
        AssetSpec(
            key=AssetKey(["raw", t]),
            deps=[boardroom_cap_etl, maxer_rosters],
            group_name="warehouse",
            kinds={"duckdb"},
        )
        for t in RAW_SOURCE_TABLES
    ],
)
def raw_warehouse(context: AssetExecutionContext):
    """Land SQLite + parquet into DuckDB `raw` schema for dbt to transform."""
    _run([sys.executable, str(WAREHOUSE_DIR / "load_raw.py")], context)
    for t in RAW_SOURCE_TABLES:
        yield MaterializeResult(asset_key=AssetKey(["raw", t]))


# --------------------------------------------------------------------------
# dbt models — sources keyed ["raw", <table>] to match the landing assets.
# --------------------------------------------------------------------------
class WarehouseTranslator(DagsterDbtTranslator):
    def get_asset_key(self, props: Mapping[str, Any]) -> AssetKey:
        if props["resource_type"] == "source":
            return AssetKey(["raw", props["name"]])
        return super().get_asset_key(props)


@dbt_assets(
    manifest=dbt_project.manifest_path,
    dagster_dbt_translator=WarehouseTranslator(),
)
def gridiron_dbt_models(context: AssetExecutionContext, dbt: DbtCliResource):
    yield from dbt.cli(["build"], context=context).stream()


# --------------------------------------------------------------------------
# Downstream modeling asset — trains the SB model on the dbt fact table,
# logs cross-validated AUC as asset metadata (visible in the Dagster UI).
# --------------------------------------------------------------------------
@asset(
    group_name="modeling",
    compute_kind="scikit-learn",
    deps=[AssetKey("fct_team_season")],
)
def sb_win_model(context: AssetExecutionContext) -> MaterializeResult:
    import duckdb
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    # Reliable, finalized window only. The cap source is sparse pre-2011, and
    # seasons after 2024 are forward cap projections (partial rosters, no real
    # SB outcome) — including either would pollute a supervised model.
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    df = con.execute(
        "SELECT * FROM main.fct_team_season WHERE season BETWEEN 2011 AND 2024"
    ).df()
    con.close()

    feature_cols = [c for c in df.columns if c.startswith("pct_")]
    X = df[feature_cols].fillna(0.0).to_numpy()
    y = df["sb_win"].astype(int).to_numpy()

    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
    auc = cross_val_score(model, X, y, cv=5, scoring="roc_auc").mean()

    context.log.info(f"5-fold CV AUC = {auc:.3f} on {len(df)} team-seasons")
    return MaterializeResult(
        metadata={
            "cv_auc": MetadataValue.float(round(float(auc), 4)),
            "n_team_seasons": MetadataValue.int(len(df)),
            "n_features": MetadataValue.int(len(feature_cols)),
            "sb_winners": MetadataValue.int(int(y.sum())),
        }
    )


# --------------------------------------------------------------------------
# PBP lakehouse — the PySpark medallion over nflfastR play-by-play (the big data).
# Independent of the cap pipeline; serves team-EPA back to the app db.
# --------------------------------------------------------------------------
@asset(group_name="lakehouse", compute_kind="pyspark")
def pbp_medallion(context: AssetExecutionContext) -> MaterializeResult:
    """Play-by-play -> Bronze/Silver/Gold Delta (PySpark), then publish team-EPA
    to the app db. Dev builds 2015-2025; the Databricks Job does 1999-2025."""
    env = dict(os.environ)
    env.setdefault("JAVA_TOOL_OPTIONS", _JAVA_OPENS)
    _run([sys.executable, "-m", "lakehouse.run_medallion",
          "--start", "2015", "--end", "2025", "--publish"], context, env=env)
    return MaterializeResult(metadata={
        "layers": MetadataValue.text("bronze -> silver -> gold (Delta)"),
        "serves": MetadataValue.text("pbp_team_season_epa, pbp_team_game_epa"),
    })


# --------------------------------------------------------------------------
# Job + daily schedule (retires the launchd 6am cron)
# --------------------------------------------------------------------------
daily_refresh = define_asset_job("daily_refresh", selection=AssetSelection.all())
daily_schedule = ScheduleDefinition(
    name="daily_refresh_6am",
    job=daily_refresh,
    cron_schedule="0 6 * * *",
)

defs = Definitions(
    assets=[
        boardroom_cap_etl,
        maxer_rosters,
        raw_warehouse,
        gridiron_dbt_models,
        sb_win_model,
        pbp_medallion,
    ],
    jobs=[daily_refresh],
    schedules=[daily_schedule],
    resources={
        "dbt": DbtCliResource(
            project_dir=dbt_project,
            dbt_executable=str(REPO / ".venv" / "bin" / "dbt"),
        )
    },
)
