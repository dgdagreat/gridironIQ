# GridironIQ PBP Lakehouse (Spark + Delta)

The cap data is small — the [dbt warehouse](../warehouse/) (DuckDB → Databricks
Delta) owns it. **Play-by-play is the big dataset**: nflfastR ships every play
since 1999 (~1.2M rows, ~20 MB/season), which is where Spark actually earns its
keep. This is a **medallion** (Bronze → Silver → Gold) in PySpark + Delta Lake
that runs identically on a laptop (`delta-spark`) and on Databricks (a scheduled
Job).

## Layers

| Layer | Table | Grain | What it is |
|---|---|---|---|
| 🥉 Bronze | `bronze/pbp` | one play | raw nflfastR, every column, + ingest metadata, partitioned by season |
| 🥈 Silver | `silver/plays` | one play | curated columns, typed, real plays with EPA, de-duped |
| 🥇 Gold | `gold/team_game_epa` | team-game | off/def EPA, success & explosive rates, pressure |
| 🥇 Gold | `gold/team_season_epa` | team-season | the season rollup |

`gridiron` still owns **ingestion** (the nflverse download + cache); the driver
lands the raw parquet through it, then Spark does the transformation — the same
split the dbt warehouse uses: *gridiron ingests, the engine transforms.*

## Run locally

```bash
uv pip install --python .venv/bin/python -e ".[spark]"   # pyspark + delta-spark (needs Java 11/17)
python -m lakehouse.run_medallion --start 2015 --end 2025
# already have the raw parquet? skip the download:
python -m lakehouse.run_medallion --skip-ingest --layers silver,gold
```

Delta tables land under `data/lakehouse/{bronze,silver,gold}/`. Query them with
Spark — or with DuckDB without Spark at all:
`SELECT * FROM delta_scan('data/lakehouse/gold/team_season_epa')`.

## Deploy to Databricks (the Job)

`databricks.yml` is a Databricks Asset Bundle that creates a **scheduled Job**
(daily, single-node — the data is ~0.5 GB) running `run_medallion.py` and writing
the Delta tables to a Unity Catalog volume:

```bash
cd lakehouse
databricks bundle validate
databricks bundle deploy -t prod
databricks bundle run pbp_medallion -t prod
```

This is the "in place of the laptop daily refresh" piece — the heavy PBP build
runs on Databricks, on a schedule, as Delta. (The small cap/roster refresh stays
in [GitHub Actions](../.github/workflows/daily-refresh.yml).)

> **Interview line:** *"I rebuilt the big-data ETL as a medallion lakehouse —
> PySpark Bronze/Silver/Gold on Delta — and scheduled it as a Databricks Job."*
