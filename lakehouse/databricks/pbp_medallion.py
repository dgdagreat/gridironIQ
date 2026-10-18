# Databricks notebook source
# MAGIC %md
# MAGIC # GridironIQ — PBP medallion (Databricks serverless)
# MAGIC Bronze → Silver → Gold over nflfastR play-by-play, written as **Unity Catalog
# MAGIC Delta tables**. Runs on **serverless** (no cluster config) and is scheduled by
# MAGIC `lakehouse/databricks.yml`. This is the cloud twin of the local `lakehouse/`
# MAGIC package — same transforms, serverless storage.

# COMMAND ----------
dbutils.widgets.text("catalog", "gridiron")
dbutils.widgets.text("schema", "pbp")
dbutils.widgets.text("start_season", "2015")
dbutils.widgets.text("end_season", "2025")

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
START = int(dbutils.widgets.get("start_season"))
END = int(dbutils.widgets.get("end_season"))
SEASONS = range(START, END + 1)
VOLUME = f"/Volumes/{CATALOG}/{SCHEMA}/raw"
PBP_URL = ("https://github.com/nflverse/nflverse-data/releases/download/pbp/"
           "play_by_play_{season}.parquet")
print(f"catalog={CATALOG}  schema={SCHEMA}  seasons={START}-{END}")

# COMMAND ----------
# Unity Catalog containers (idempotent)
spark.sql(f"CREATE CATALOG IF NOT EXISTS {CATALOG}")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.raw")

# COMMAND ----------
# INGEST — fetch raw nflfastR parquet into the volume (the cluster has egress).
# Skips files already present so re-runs are cheap.
import os
import urllib.request

os.makedirs(VOLUME, exist_ok=True)
for s in SEASONS:
    dest = f"{VOLUME}/pbp_{s}.parquet"
    if os.path.exists(dest):
        print(f"cached  {s}")
        continue
    try:
        urllib.request.urlretrieve(PBP_URL.format(season=s), dest)
        print(f"fetched {s}")
    except Exception as e:  # a missing/old season shouldn't kill the run
        print(f"[warn] {s}: {e}")

# COMMAND ----------
# BRONZE — land raw plays as-is (every column), partitioned by season.
from pyspark.sql import functions as F

bronze = (spark.read.option("mergeSchema", "true").parquet(f"{VOLUME}/pbp_*.parquet")
          .withColumn("_ingested_at", F.current_timestamp()))
(bronze.write.format("delta").mode("overwrite").option("overwriteSchema", "true")
 .partitionBy("season").saveAsTable(f"{CATALOG}.{SCHEMA}.bronze_pbp"))
print("bronze_pbp rows:", bronze.count())

# COMMAND ----------
# SILVER — curated, typed, de-duped real plays with an EPA + explosive flag.
KEEP = ["season", "week", "game_id", "play_id", "posteam", "defteam", "play_type",
        "down", "ydstogo", "yardline_100", "yards_gained", "epa", "wpa", "success",
        "pass", "rush", "qb_dropback", "qb_hit", "sack", "complete_pass",
        "touchdown", "interception", "fumble_lost", "air_yards", "yards_after_catch"]

b = spark.read.table(f"{CATALOG}.{SCHEMA}.bronze_pbp")
s = b.select(*[c for c in KEEP if c in b.columns]).filter(
    F.col("epa").isNotNull() & F.col("posteam").isNotNull() & F.col("defteam").isNotNull())
for c in ("epa", "wpa", "yards_gained", "air_yards", "yards_after_catch"):
    if c in s.columns:
        s = s.withColumn(c, F.col(c).cast("double"))
_is_pass = F.coalesce(F.col("pass").cast("int"), F.lit(0)) == 1
s = s.withColumn("explosive",
                 F.when(_is_pass & (F.col("yards_gained") >= 20), 1)
                  .when(~_is_pass & (F.col("yards_gained") >= 10), 1).otherwise(0))
s = s.dropDuplicates(["game_id", "play_id"])
(s.write.format("delta").mode("overwrite").option("overwriteSchema", "true")
 .partitionBy("season").saveAsTable(f"{CATALOG}.{SCHEMA}.silver_plays"))
print("silver_plays rows:", s.count())

# COMMAND ----------
# GOLD — team-game and team-season EPA (offense + defense joined per team).
def team_table(df, grp):
    is_pass = F.coalesce(F.col("pass").cast("int"), F.lit(0)) == 1
    is_rush = F.coalesce(F.col("rush").cast("int"), F.lit(0)) == 1
    off = df.groupBy(*grp, F.col("posteam").alias("team")).agg(
        F.count("*").alias("off_plays"),
        F.round(F.avg("epa"), 4).alias("off_epa_play"),
        F.round(F.avg(F.when(is_pass, F.col("epa"))), 4).alias("off_pass_epa"),
        F.round(F.avg(F.when(is_rush, F.col("epa"))), 4).alias("off_rush_epa"),
        F.round(F.avg(F.col("success").cast("double")), 4).alias("off_success_rate"),
        F.round(F.avg(F.col("explosive").cast("double")), 4).alias("off_explosive_rate"))
    dropbacks = F.sum(F.coalesce(F.col("qb_dropback").cast("int"), F.lit(0)))
    pressures = (F.sum(F.coalesce(F.col("qb_hit").cast("int"), F.lit(0)))
                 + F.sum(F.coalesce(F.col("sack").cast("int"), F.lit(0))))
    deff = df.groupBy(*grp, F.col("defteam").alias("team")).agg(
        F.count("*").alias("def_plays"),
        F.round(F.avg("epa"), 4).alias("def_epa_play_allowed"),
        F.round(F.avg(F.col("success").cast("double")), 4).alias("def_success_allowed"),
        F.round(F.when(dropbacks > 0, pressures / dropbacks), 4).alias("def_pressure_rate"))
    return (off.join(deff, grp + ["team"], "outer").withColumn(
        "net_epa_play", F.round(F.col("off_epa_play") - F.col("def_epa_play_allowed"), 4)))


plays = spark.read.table(f"{CATALOG}.{SCHEMA}.silver_plays")
team_game = team_table(plays, ["season", "week", "game_id"])
team_season = team_table(plays, ["season"])
(team_game.write.format("delta").mode("overwrite").option("overwriteSchema", "true")
 .partitionBy("season").saveAsTable(f"{CATALOG}.{SCHEMA}.gold_team_game_epa"))
(team_season.write.format("delta").mode("overwrite").option("overwriteSchema", "true")
 .partitionBy("season").saveAsTable(f"{CATALOG}.{SCHEMA}.gold_team_season_epa"))
print("gold_team_game rows:", team_game.count(),
      " gold_team_season rows:", team_season.count())

# COMMAND ----------
# MAGIC %md ### Headline: most efficient teams (latest season)
# MAGIC Most efficient offenses/defenses by net EPA/play — the on-field complement to
# MAGIC the cap-efficiency marts.

# COMMAND ----------
display(spark.sql(f"""
  SELECT season, team, off_epa_play, def_epa_play_allowed, net_epa_play
  FROM {CATALOG}.{SCHEMA}.gold_team_season_epa
  WHERE season = {END}
  ORDER BY net_epa_play DESC
  LIMIT 10
"""))
