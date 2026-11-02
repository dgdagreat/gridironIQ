"""Silver — clean, typed, analysis-ready plays.

From Bronze's ~370 raw columns we keep the stable, meaningful ones, cast types,
filter to real scrimmage plays with a computed EPA, standardize keys, and
de-duplicate on (game_id, play_id). This is the grain the Gold aggregations and
the Film Room metrics both reason about.
"""

from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from lakehouse import paths

#: Stable nflfastR columns Silver carries forward (selected if present).
_KEEP = [
    "season", "week", "game_id", "play_id", "posteam", "defteam",
    "home_team", "away_team", "play_type", "down", "ydstogo", "yardline_100",
    "yards_gained", "epa", "wpa", "success", "pass", "rush", "qb_dropback",
    "qb_hit", "sack", "complete_pass", "incomplete_pass", "interception",
    "fumble_lost", "touchdown", "pass_touchdown", "rush_touchdown", "penalty",
    "air_yards", "yards_after_catch", "cpoe",
]


def build_silver(spark: SparkSession) -> DataFrame:
    """Transform Bronze -> Silver Delta table (partitioned by season)."""
    bronze = spark.read.format("delta").load(paths.BRONZE_PBP)
    cols = [c for c in _KEEP if c in bronze.columns]
    df = bronze.select(*cols)

    # Keep real scrimmage plays with a measurable outcome.
    df = df.filter(F.col("epa").isNotNull())
    if "play_type" in df.columns:
        # Keep the same scrimmage-play denominator used by Film Room analytics.
        df = df.filter(F.col("play_type").isin("run", "pass"))
        is_pass = F.col("play_type") == "pass"
        is_rush = F.col("play_type") == "run"
    else:
        # Older or partial source schemas may omit play_type but retain nflfastR's
        # pass/rush flags. Require one of those flags rather than guessing.
        is_pass = (F.coalesce(F.col("pass").cast("int"), F.lit(0)) == 1
                   if "pass" in df.columns else F.lit(False))
        is_rush = (F.coalesce(F.col("rush").cast("int"), F.lit(0)) == 1
                   if "rush" in df.columns else F.lit(False))
        df = df.filter(is_pass | is_rush)
    df = df.filter(F.col("posteam").isNotNull() & F.col("defteam").isNotNull())

    # Numeric casts (nflfastR mixes doubles / strings across years).
    for c in ("epa", "wpa", "yards_gained", "air_yards", "yards_after_catch",
              "cpoe", "ydstogo", "yardline_100"):
        if c in df.columns:
            df = df.withColumn(c, F.col(c).cast("double"))
    for c in ("down", "week", "play_id"):
        if c in df.columns:
            df = df.withColumn(c, F.col(c).cast("int"))

    # An explosive play: 20+ pass yards or 10+ rush yards. Do not treat
    # non-pass events as rushes.
    df = df.withColumn(
        "explosive",
        F.when(is_pass & (F.col("yards_gained") >= 20), F.lit(1))
         .when(is_rush & (F.col("yards_gained") >= 10), F.lit(1))
         .otherwise(F.lit(0)))

    df = df.dropDuplicates(["game_id", "play_id"])

    (df.write.format("delta").mode("overwrite")
     .option("overwriteSchema", "true")
     .partitionBy("season")
     .save(paths.SILVER_PLAYS))
    return df
