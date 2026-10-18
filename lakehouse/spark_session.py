"""A Delta-enabled Spark session — the same code runs locally and on Databricks.

Locally we spin up `local[*]` and wire in Delta Lake via `delta-spark`. On a
Databricks cluster a SparkSession already exists with Delta built in, so we just
reuse it. Nothing else in the medallion needs to know where it's running.
"""

from __future__ import annotations

import os

from pyspark.sql import SparkSession


def get_spark(app_name: str = "gridiron-pbp-medallion") -> SparkSession:
    """Return an active Delta-enabled SparkSession (reused on Databricks)."""
    active = SparkSession.getActiveSession()
    if active is not None:          # on Databricks / an existing session
        return active

    builder = (
        SparkSession.builder.appName(app_name)
        .master(os.environ.get("SPARK_MASTER", "local[*]"))
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog",
                "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .config("spark.sql.shuffle.partitions",
                os.environ.get("SPARK_SHUFFLE_PARTITIONS", "8"))
        .config("spark.ui.showConsoleProgress", "false")
    )
    # Pull the matching Delta jars on first local run (no-op if already present).
    from delta import configure_spark_with_delta_pip
    return configure_spark_with_delta_pip(builder).getOrCreate()
