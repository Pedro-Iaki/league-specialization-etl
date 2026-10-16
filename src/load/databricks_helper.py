import os
from datetime import timedelta
from pathlib import Path
from time import monotonic
from typing import Any

import pandas as pd
from databricks import sql
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config
from databricks.sdk.service.jobs import RunResultState
from dotenv import load_dotenv
from loguru import logger
from requests.exceptions import Timeout

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "config" / "DATABRICKS_CONFIG.env"
MAX_JOB_ATTEMPTS = 3


def get_config() -> dict[str, str | None]:
    """Read config/DATABRICKS_CONFIG.env, preserving process environment overrides."""
    load_dotenv(CONFIG_PATH)
    return {
        "host": os.getenv("HOST"),
        "http_path": os.getenv("HTTP_PATH"),
        "token": os.getenv("TOKEN"),
    }


def get_connection():
    """Require host, warehouse HTTP path and token before opening a SQL connection."""
    config = get_config()
    missing = [key for key, value in config.items() if value in (None, "")]
    if missing:
        raise ValueError("Missing Databricks connection config: " + ", ".join(missing))

    cfg = Config(host=config["host"], token=config["token"])
    return sql.connect(
        server_hostname=config["host"],
        http_path=config["http_path"],
        credentials_provider=lambda: cfg.authenticate,
    )


def use_catalog_and_schema(cursor: Any, catalog: str, schema: str) -> None:
    cursor.execute(f"USE CATALOG {catalog}")
    cursor.execute(f"USE SCHEMA {schema}")


def upload_parquet(local_path: str, dbfs_path: str) -> None:
    get_workspace_client().files.upload_from(dbfs_path, local_path, overwrite=True)


def get_workspace_client() -> WorkspaceClient:
    cfg = get_config()
    return WorkspaceClient(config=Config(host=cfg["host"], token=cfg["token"]))


def run_job(job_id: int, timeout_seconds: int, job_name: str) -> bool:
    try:
        workspace = get_workspace_client()
    except Exception as error:  # noqa: BLE001 - invalid workspace credentials must stop loading
        logger.error(f"Cannot start {job_name} job {job_id}: {error}")
        return False
    for attempt in range(1, MAX_JOB_ATTEMPTS + 1):
        run_id = None
        try:
            waiting = workspace.jobs.run_now(job_id=job_id)
            run_id = waiting.run_id
            started_at = monotonic()
            logger.info(f"{job_name} job started (attempt {attempt}/{MAX_JOB_ATTEMPTS}).")
            logger.debug(f"{job_name} job {job_id}, run {run_id}.")
            run = waiting.result(timeout=timedelta(seconds=timeout_seconds))
            if run.state.result_state != RunResultState.SUCCESS:
                raise RuntimeError(f"Job ended with {run.state.result_state}")
            logger.info(f"{job_name} job completed in {(monotonic() - started_at) / 60:.1f} min.")
            return True
        except (TimeoutError, Timeout) as error:
            logger.error(
                f"{job_name} job {job_id}, run {run_id} timed out: {error}. Stopping this job check; check the run in Databricks before retrying."
            )
            return False
        except Exception as error:  # noqa: BLE001 - SDK submission and job failures have several error types
            logger.error(f"{job_name} job {job_id}, run {run_id}, attempt {attempt} failed: {error}")
    return False


PANDAS_TO_SPARK_TYPES = {
    "object": "STRING",
    "string": "STRING",
    "int64": "BIGINT",
    "int32": "INT",
    "int16": "SMALLINT",
    "int8": "TINYINT",
    "float64": "DOUBLE",
    "float32": "FLOAT",
    "bool": "BOOLEAN",
    "datetime64[ns]": "TIMESTAMP",
    "timedelta64[ns]": "STRING",
}


def infer_sql_schema(df: pd.DataFrame) -> str:
    column_defs = []
    for col_name, dtype in df.dtypes.items():
        if str(dtype).lower() == "object" and _is_list_like_column(df[col_name]):
            sql_type = "ARRAY<STRING>"
        else:
            sql_type = PANDAS_TO_SPARK_TYPES.get(str(dtype).lower(), "STRING")
        column_defs.append(f"`{col_name}` {sql_type}")
    return ",\n            ".join(column_defs)


def _is_list_like_column(series: pd.Series) -> bool:
    non_null = series.dropna()
    if non_null.empty:
        return False
    return bool(non_null.apply(lambda v: isinstance(v, (list, tuple))).all())
