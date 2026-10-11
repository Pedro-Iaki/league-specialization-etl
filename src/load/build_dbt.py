"""Run the warehouse build after a confirmed load, or retry the build alone."""

import os
import sys
from pathlib import Path

from dotenv import dotenv_values

from load.databricks_helper import run_job
from pydantic_models import DbtConfigManifest

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "EXTRACTION_CONFIG.env"


def run_dbt() -> bool:
    settings = {**dotenv_values(CONFIG_PATH), **os.environ}
    config = DbtConfigManifest.model_validate(
        {
            "dbt_job_id": settings.get("DBT_JOB_ID"),
            "dbt_timeout_seconds": settings.get("DBT_TIMEOUT_SECONDS", "1800"),
        }
    )
    return run_job(config.dbt_job_id, config.dbt_timeout_seconds, "dbt")


if __name__ == "__main__":
    sys.exit(0 if run_dbt() else 1)
