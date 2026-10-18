"""Gold — team EPA features from the Silver plays.

Two analytics-ready Delta tables, each with an offensive and a defensive side of
the ball joined per team:

  * ``team_game_epa``   — one row per (season, week, game_id, team)
  * ``team_season_epa`` — one row per (season, team)

These are the exact signals the thesis cares about (how efficiently a team moves
and stops the ball) at a grain the app and models can join straight onto.
"""

from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql import Column

from lakehouse import paths


def _rate(numer: Column, denom: Column) -> Column:
    return F.when(denom > 0, numer / denom).otherwise(F.lit(None))


def _offense(plays: DataFrame, grp: list[str]) -> DataFrame:
    is_pass = F.coalesce(F.col("pass").cast("int"), F.lit(0)) == 1
    is_rush = F.coalesce(F.col("rush").cast("int"), F.lit(0)) == 1
    return (plays.groupBy(*grp, F.col("posteam").alias("team")).agg(
        F.count("*").alias("off_plays"),
        F.round(F.avg("epa"), 4).alias("off_epa_play"),
        F.round(F.avg(F.when(is_pass, F.col("epa"))), 4).alias("off_pass_epa"),
        F.round(F.avg(F.when(is_rush, F.col("epa"))), 4).alias("off_rush_epa"),
        F.round(F.avg(F.col("success").cast("double")), 4).alias("off_success_rate"),
        F.round(F.avg(F.col("explosive").cast("double")), 4).alias("off_explosive_rate"),
    ))


def _defense(plays: DataFrame, grp: list[str]) -> DataFrame:
    dropbacks = F.sum(F.coalesce(F.col("qb_dropback").cast("int"), F.lit(0)))
    pressures = (F.sum(F.coalesce(F.col("qb_hit").cast("int"), F.lit(0)))
                 + F.sum(F.coalesce(F.col("sack").cast("int"), F.lit(0))))
    return (plays.groupBy(*grp, F.col("defteam").alias("team")).agg(
        F.count("*").alias("def_plays"),
        F.round(F.avg("epa"), 4).alias("def_epa_play_allowed"),
        F.round(F.avg(F.col("success").cast("double")), 4).alias("def_success_allowed"),
        F.round(F.avg(F.col("explosive").cast("double")), 4).alias("def_explosive_allowed"),
        F.round(_rate(pressures, dropbacks), 4).alias("def_pressure_rate"),
    ))


def _team_table(plays: DataFrame, grp: list[str]) -> DataFrame:
    off = _offense(plays, grp)
    deff = _defense(plays, grp)
    keys = grp + ["team"]
    return (off.join(deff, keys, "outer")
            .withColumn("net_epa_play",
                        F.round(F.col("off_epa_play") - F.col("def_epa_play_allowed"), 4))
            .orderBy(*grp, F.col("net_epa_play").desc_nulls_last()))


def build_gold(spark: SparkSession) -> tuple[DataFrame, DataFrame]:
    """Transform Silver -> the two Gold Delta tables. Returns (team_game, team_season)."""
    plays = spark.read.format("delta").load(paths.SILVER_PLAYS)

    team_game = _team_table(plays, ["season", "week", "game_id"])
    (team_game.write.format("delta").mode("overwrite")
     .option("overwriteSchema", "true").partitionBy("season")
     .save(paths.GOLD_TEAM_GAME))

    team_season = _team_table(plays, ["season"])
    (team_season.write.format("delta").mode("overwrite")
     .option("overwriteSchema", "true").partitionBy("season")
     .save(paths.GOLD_TEAM_SEASON))

    return team_game, team_season
