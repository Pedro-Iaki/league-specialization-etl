"""Start the ingestion-only Databricks job and check its terminal result."""

import os
from pathlib import Path

from dotenv import dotenv_values

from load.databricks_helper import run_job
from pydantic_models import IngestionConfigManifest

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "EXTRACTION_CONFIG.env"


def get_ingestion_config() -> IngestionConfigManifest:
    settings = {**dotenv_values(CONFIG_PATH), **os.environ}
    return IngestionConfigManifest.model_validate(
        {
            "ingest_job_id": settings.get("INGEST_JOB_ID"),
            "ingestion_timeout_seconds": settings.get("INGESTION_TIMEOUT_SECONDS", "900"),
        }
    )


def run_ingestion(job_id: int, timeout_seconds: int) -> bool:
    return run_job(job_id, timeout_seconds, "Ingestion")
