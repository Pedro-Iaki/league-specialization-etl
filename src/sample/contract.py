"""Small explicit Arrow contracts shared by generation and the sample-only loader."""
from __future__ import annotations

import csv
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pyarrow as pa

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = REPO_ROOT / "data" / "business_sample"
SEED_DIR = REPO_ROOT / "league_pipeline" / "seeds"
MONEY = pa.decimal128(18, 2)
UTC = pa.timestamp("us", tz="UTC")
COHORT_SCHEMA = pa.schema([
    ("player_id", pa.string()), ("region", pa.string()), ("queue", pa.string()),
    ("tier", pa.string()), ("main_role", pa.string()), ("active_playstyle", pa.string()),
    ("snapshot_date", pa.date32()), ("as_of_date", pa.date32()),
    ("active_primary_champion_key", pa.int64()), ("active_primary_champion_name", pa.string()),
    ("active_top1_share", pa.float64()), ("active_normalized_entropy", pa.float64()),
    ("champions_with_mastery", pa.int64()), ("total_mastery_points", pa.int64()),
    ("alltime_top1_share", pa.float64()), ("games_per_day_recent", pa.float64()),
    ("ranked_mastery_share", pa.float64()),
])
OPTIONAL_REAL_FEATURES = {"ranked_mastery_share", "games_per_day_recent"}
REQUIRED_REAL_FEATURES = [name for name in COHORT_SCHEMA.names if name not in OPTIONAL_REAL_FEATURES]
PLAYER_SCHEMA = pa.schema([
    *COHORT_SCHEMA,
    ("simulated_customer_type", pa.string()), ("simulated_owned_champions", pa.int64()),
    ("scenario_id", pa.string()), ("purchase_window_start", pa.date32()),
    ("purchase_window_end", pa.date32()), ("scenario_metadata", pa.string()),
])
TRANSACTION_SCHEMA = pa.schema([
    ("transaction_id", pa.string()), ("player_id", pa.string()), ("product_id", pa.string()),
    ("region_at_purchase", pa.string()), ("currency_id", pa.string()),
    ("original_price", MONEY), ("amount_spent", MONEY), ("amount_usd", MONEY),
    ("occurred_at", UTC), ("scenario_id", pa.string()),
])
SAMPLE_TABLES = {
    "transactions": "league_pipeline.raw.transactions",
    "business_sample_players": "league_pipeline.raw.business_sample_players",
}


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, allow_nan=False).encode()).hexdigest()


def read_seeds() -> tuple[dict, dict]:
    with (SEED_DIR / "sample_currencies.csv").open(encoding="utf-8", newline="") as handle:
        currencies = {row["currency_id"]: row for row in csv.DictReader(handle)}
    with (SEED_DIR / "sample_products.csv").open(encoding="utf-8", newline="") as handle:
        products = {row["product_id"]: row for row in csv.DictReader(handle)}
    for row in products.values():
        row["sample_original_price"] = Decimal(row["sample_original_price"])
        row["sample_amount_usd"] = Decimal(row["sample_amount_usd"]) if row["sample_amount_usd"] else None
        if row["purchase_currency_id"] not in currencies:
            raise ValueError("Product seed references an unknown currency")
    return currencies, products


def sql_schema(schema: pa.Schema) -> str:
    types = {pa.string(): "STRING", pa.int64(): "BIGINT", pa.float64(): "DOUBLE",
             pa.date32(): "DATE", UTC: "TIMESTAMP", MONEY: "DECIMAL(18,2)"}
    return ", ".join(f"`{field.name}` {types[field.type]}" for field in schema)
