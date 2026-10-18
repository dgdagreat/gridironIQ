"""Bronze — land raw nflfastR play-by-play as Delta, as-is.

Bronze keeps the source faithful: every column, no business logic, just the raw
plays plus an ingestion timestamp and a partition on ``season``. nflfastR's schema
drifts a little across 25+ years, so we read with ``mergeSchema`` and union.
"""

from __future__ import annotations

import glob

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from lakehouse import paths


def _season_from_path(p: str) -> int:
    return int(p.rsplit("pbp_", 1)[1].split(".", 1)[0])


def build_bronze(spark: SparkSession, seasons: range | list[int] | None = None) -> DataFrame:
    """Read raw ``pbp_{season}.parquet`` files and write the Bronze Delta table.

    ``seasons`` defaults to every season with a raw file present in RAW_PBP_DIR.
    Returns the bronze DataFrame.
    """
    available = {_season_from_path(p): p
                 for p in glob.glob(f"{paths.RAW_PBP_DIR}/pbp_*.parquet")}
    wanted = sorted(available) if seasons is None else [s for s in seasons if s in available]
    if not wanted:
        raise FileNotFoundError(
            f"No raw PBP parquet found in {paths.RAW_PBP_DIR}. Run the driver "
            "(it calls gridiron.load_pbp) or land the files first.")

    frames = []
    for season in wanted:
        df = (spark.read.parquet(available[season])
              .withColumn("season", F.lit(season))
              .withColumn("_ingested_at", F.current_timestamp())
              .withColumn("_source_file", F.lit(f"pbp_{season}.parquet")))
        frames.append(df)

    # Union by name so column drift across seasons is tolerated (missing -> null).
    bronze = frames[0]
    for df in frames[1:]:
        bronze = bronze.unionByName(df, allowMissingColumns=True)

    (bronze.write.format("delta").mode("overwrite")
     .option("overwriteSchema", "true")
     .partitionBy("season")
     .save(paths.BRONZE_PBP))
    return bronze
