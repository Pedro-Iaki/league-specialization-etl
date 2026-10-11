"""Validate files before any write and gate serving on a complete matching warehouse sample."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq

from .contract import PLAYER_SCHEMA, TRANSACTION_SCHEMA, read_seeds
from .generate_transactions import normalize_cohort


def validate_files(directory: Path) -> tuple[object, object, dict]:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    players = pq.read_table(directory / "business_sample_players.parquet")
    events = pq.read_table(directory / "transactions.parquet")
    for name, table, schema in (("players", players, PLAYER_SCHEMA), ("transactions", events, TRANSACTION_SCHEMA)):
        if not table.schema.equals(schema, check_metadata=False) or not table.num_rows:
            raise ValueError(f"Invalid {name} columns/types or empty file")
    normalize_cohort(players, manifest["queue"])
    player_rows, event_rows = players.to_pylist(), events.to_pylist()
    player_by_id = {row["player_id"]: row for row in player_rows}
    ids = [row["transaction_id"] for row in event_rows]
    if any(not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("transaction_id must be unique and non-null")
    if len(player_rows) != manifest["player_count"] or len(event_rows) != manifest["transaction_count"]:
        raise ValueError("Scenario manifest row counts do not match the files")
    currencies, products = read_seeds()
    cash_total, fiat_count = Decimal(0), 0
    be_players = set()
    for player in player_rows:
        metadata = json.loads(player["scenario_metadata"])
        if any(manifest.get(key) != value for key, value in metadata.items()):
            raise ValueError("Cohort metadata does not match the scenario manifest")
        if (player["scenario_id"] != manifest["scenario_id"]
                or player["as_of_date"].isoformat() != manifest["as_of_date"]
                or not manifest["min_snapshot_date"] <= player["snapshot_date"].isoformat() <= manifest["max_snapshot_date"]
                or player["purchase_window_start"].isoformat() != manifest["purchase_window_start"]
                or player["purchase_window_end"] != player["as_of_date"]
                or (player["purchase_window_end"] - player["purchase_window_start"]).days != 59):
            raise ValueError("Cohort scenario/date window mismatch")
        if player["simulated_customer_type"] not in {"sardine", "dolphin", "whale"} \
                or player["simulated_owned_champions"] is None or not 20 <= player["simulated_owned_champions"] <= 200:
            raise ValueError("Invalid simulated customer type or ownership")
    end = datetime.fromisoformat(manifest["as_of_date"]).replace(tzinfo=timezone.utc) + timedelta(days=1)
    for event in event_rows:
        player = player_by_id.get(event["player_id"])
        product = products.get(event["product_id"])
        currency = currencies.get(event["currency_id"])
        if player is None or product is None or currency is None:
            raise ValueError("Transaction has unknown cohort, product or currency ID")
        if event["scenario_id"] != manifest["scenario_id"] or event["region_at_purchase"] != player["region"]:
            raise ValueError("Transaction scenario/region mismatch")
        if event["currency_id"] != product["purchase_currency_id"]:
            raise ValueError("Transaction currency differs from its SKU")
        if event["occurred_at"] is None or not datetime(2000, 1, 1, tzinfo=timezone.utc) <= event["occurred_at"] < end:
            raise ValueError("Transaction date is outside the scenario")
        price, amount, usd = event["original_price"], event["amount_spent"], event["amount_usd"]
        if price is None or amount is None or not Decimal(0) <= amount <= price <= Decimal(1000000):
            raise ValueError("Broken or negative event amounts")
        if currency["currency_kind"] == "fiat":
            if usd is None or not Decimal(0) <= usd <= Decimal(1000000):
                raise ValueError("Fiat events require nonnegative source-provided USD")
            if event["currency_id"] == "USD" and usd != amount:
                raise ValueError("USD events must preserve source USD = amount paid")
            cash_total += usd
            fiat_count += 1
        elif usd is not None:
            raise ValueError("Game currencies must not carry cash valuation")
        if event["currency_id"] == "L_BE" and product["category"] == "champion":
            be_players.add(event["player_id"])
    if be_players != set(player_by_id):
        raise ValueError("Every sampled ranked player must have BE acquisition history")
    if cash_total != Decimal(manifest["cash_spent_usd_alltime"]) or fiat_count != manifest["fiat_transaction_count"]:
        raise ValueError("Source USD totals/counts do not reconcile to the manifest")
    for field, value in (("history_start_at", min(row["occurred_at"] for row in event_rows)),
                         ("history_end_at", max(row["occurred_at"] for row in event_rows))):
        if value != datetime.fromisoformat(manifest[field]):
            raise ValueError("Scenario history dates differ from generated events")
    return players, events, manifest


def warehouse_metadata(cursor, require_gold: bool = True) -> dict:
    """The cohort is written last. Empty/inconsistent raw or stale Gold blocks serving."""
    cursor.execute("""
        select count(*), count(distinct player_id), count(distinct scenario_id),
               count(distinct scenario_metadata), max(scenario_metadata), max(scenario_id)
        from league_pipeline.raw.business_sample_players
    """)
    count, unique_count, scenarios, metadata_count, encoded, scenario = cursor.fetchone()
    if not count or count != unique_count or scenarios != 1 or metadata_count != 1 or encoded is None:
        raise ValueError("Business sample load is incomplete: frozen cohort completion marker is absent/inconsistent")
    metadata = json.loads(encoded)
    if count != metadata["player_count"] or scenario != metadata["scenario_id"]:
        raise ValueError("Business sample cohort does not match scenario metadata")
    cursor.execute("""
        select count(*), count(distinct transaction_id), count(distinct scenario_id), max(scenario_id),
               sum(case when currency_id in ('USD', 'BRL') then amount_usd else 0 end),
               count(case when currency_id in ('USD', 'BRL') then 1 end)
        from league_pipeline.raw.transactions
    """)
    tx_count, unique_tx, scenarios, tx_scenario, usd, fiat_count = cursor.fetchone()
    if (tx_count != metadata["transaction_count"] or unique_tx != tx_count or scenarios != 1 or tx_scenario != scenario
            or Decimal(str(usd or 0)) != Decimal(metadata["cash_spent_usd_alltime"])
            or fiat_count != metadata["fiat_transaction_count"]):
        raise ValueError("Business sample load is incomplete: transaction scenario/count/USD mismatch")
    if require_gold:
        cursor.execute("""
            select count(*), count(distinct player_id), count(distinct scenario_id), max(scenario_id),
                   sum(purchase_count_alltime), sum(cash_spent_usd_alltime), sum(cash_purchase_count_alltime)
            from league_pipeline.gold.mart_player_spending
        """)
        gold_count, gold_unique, scenarios, gold_scenario, purchase_count, usd, fiat_count = cursor.fetchone()
        if (gold_count != count or gold_unique != count or scenarios != 1 or gold_scenario != scenario
                or purchase_count != tx_count or Decimal(str(usd or 0)) != Decimal(metadata["cash_spent_usd_alltime"])
                or fiat_count != metadata["fiat_transaction_count"]):
            raise ValueError("Business sample Gold is stale or incomplete; run dbt build --select tag:business_sample")
    return metadata
