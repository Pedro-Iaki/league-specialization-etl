import os
from pathlib import Path
from typing import Any

import pandas as pd
from databricks import sql
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "config" / "DATABRICKS_CONFIG.env"


def get_config() -> dict[str, str | None]:
    """Resolve Databricks connection settings from env vars or explicit args."""
    load_dotenv(CONFIG_PATH)
    return {
        "host": os.getenv("HOST"),
        "http_path": os.getenv("HTTP_PATH"),
        "token": os.getenv("TOKEN"),
    }


def get_connection():
    """Create a Databricks SQL connection from environment or explicit parameters."""
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
    """Set the active catalog and schema on a Databricks cursor."""
    cursor.execute(f"USE CATALOG {catalog}")
    cursor.execute(f"USE SCHEMA {schema}")


def upload_parquet(local_path: str, dbfs_path: str) -> None:
    cfg = get_config()
    w = WorkspaceClient(config=Config(host=cfg["host"], token=cfg["token"]))
    with open(local_path, "rb") as f:
        w.files.upload(dbfs_path, f, overwrite=True)


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
