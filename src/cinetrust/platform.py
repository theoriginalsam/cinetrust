"""Thin Databricks helpers so job scripts run both as serverless jobs and locally via Connect."""

from __future__ import annotations

import os


def on_databricks() -> bool:
    return "DATABRICKS_RUNTIME_VERSION" in os.environ


def get_spark():
    if on_databricks():
        from pyspark.sql import SparkSession

        return SparkSession.builder.getOrCreate()
    from databricks.connect import DatabricksSession

    return DatabricksSession.builder.getOrCreate()


def get_secret(scope: str, key: str, env_var: str) -> str | None:
    """Environment variable first (local runs), then the Databricks secret scope."""
    if os.environ.get(env_var):
        return os.environ[env_var].strip()
    if not on_databricks():
        return None
    try:
        from databricks.sdk.runtime import dbutils

        # Pasted keys often carry a trailing newline or space; APIs reject them as invalid.
        return dbutils.secrets.get(scope, key).strip() or None
    except Exception:
        return None


def fq(catalog: str, schema: str, name: str) -> str:
    return f"`{catalog}`.`{schema}`.`{name}`"


def write_table(spark, pdf, table: str, mode: str = "overwrite") -> None:
    (spark.createDataFrame(pdf).write.mode(mode)
        .option("overwriteSchema", "true" if mode == "overwrite" else "false")
        .option("mergeSchema", "true" if mode == "append" else "false")
        .saveAsTable(table))
