"""Read the extraction pipeline's shared configuration without changing the environment."""

import os
from pathlib import Path

from dotenv import dotenv_values

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "EXTRACTION_CONFIG.env"


def get_configs(config_path: Path = CONFIG_PATH) -> dict:
    """Read the selected file; explicit process environment values take precedence."""
    settings = {**dotenv_values(config_path), **os.environ}
    fields = {
        "RIOT_API_KEY": "api_key",
        "PLAYERS_FETCH_DEPTH": "players_fetch_depth",
        "MASTERY_TASK_LIMIT": "mastery_task_limit",
        "FULL_VERIFICATION": "full_check",
        "REGION": "region",
        "QUEUE": "queue",
        "FRESHNESS_THRESHOLD_MINUTES": "freshness_threshold_minutes",
        "RUNS_PER_LOAD": "runs_per_load",
        "MAX_REFRESH_SCALE": "max_refresh_scale",
        "INGEST_JOB_ID": "ingest_job_id",
        "INGESTION_TIMEOUT_SECONDS": "ingestion_timeout_seconds",
        "DBT_JOB_ID": "dbt_job_id",
        "DBT_TIMEOUT_SECONDS": "dbt_timeout_seconds",
    }
    config = {field: settings[key] for key, field in fields.items() if key in settings}
    for key in ("TIERS", "DIVISIONS"):
        if key in settings:
            config[key.lower()] = [value.strip() for value in (settings[key] or "").split(",")]
    return config
