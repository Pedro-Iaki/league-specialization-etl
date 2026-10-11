from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from load.load_business_sample import load_sample, replace_sample_table
from sample.contract import COHORT_SCHEMA, SAMPLE_TABLES, TRANSACTION_SCHEMA
from sample.generate_transactions import generate, normalize_cohort, select_complete_cohort
from sample.validation import validate_files, warehouse_metadata


@pytest.fixture
def cohort():
    rows = []
    for index in range(40):
        row = dict.fromkeys(COHORT_SCHEMA.names)
        row.update(player_id=f"private-{index:03d}", region="BR1" if index % 2 else "NA1",
                   queue="RANKED_SOLO_5x5", tier="GOLD", snapshot_date=date(2026, 9, 29),
                   as_of_date=date(2026, 9, 29), champions_with_mastery=30 + index,
                   main_role="Middle", active_primary_champion_key=103, total_mastery_points=900_000,
                   active_primary_champion_name="Ahri", active_playstyle="specialist",
                   active_top1_share=0.6, active_normalized_entropy=0.4,
                   alltime_top1_share=0.5, games_per_day_recent=2.0, ranked_mastery_share=0.7)
        rows.append(row)
    return pa.Table.from_pylist(rows, schema=COHORT_SCHEMA)


def test_complete_cohort_has_no_cap_preserves_dates_and_rejects_missing_features(cohort):
    rows = []
    for index in range(1205):
        row = cohort.to_pylist()[0].copy()
        row["player_id"] = f"complete-{index}"
        row["snapshot_date"] = date(2026, 9, 26) if index % 2 else date(2026, 9, 29)
        row["ranked_mastery_share"] = None
        row["games_per_day_recent"] = None
        rows.append(row)
    for column, value in (("active_primary_champion_name", None), ("active_playstyle", "insufficient activity"),
                          ("games_per_day_recent", float("nan")), ("active_top1_share", 1.1)):
        row = rows[0].copy()
        row.update(player_id=f"invalid-{column}")
        row[column] = value
        rows.append(row)
    complete = select_complete_cohort(pa.Table.from_pylist(rows, schema=COHORT_SCHEMA))
    assert complete.num_rows == 1205
    assert complete["ranked_mastery_share"].null_count == 1205
    assert complete["games_per_day_recent"].null_count == 1205
    assert len(set(complete["snapshot_date"].to_pylist())) == 2
    with pytest.raises(ValueError, match="required real features"):
        normalize_cohort(pa.Table.from_pylist([rows[-4]], schema=COHORT_SCHEMA))
    events, players, manifest = generate(complete.slice(0, 2))
    assert manifest["min_snapshot_date"] == "2026-09-26"
    assert manifest["max_snapshot_date"] == "2026-09-29"
    assert players.num_rows == 2 and events.num_rows > 0
    assert manifest["observed_optional_feature_counts"] == {"games_per_day_recent": 0, "ranked_mastery_share": 0}


def write_sample(directory, events, players, manifest):
    pq.write_table(events, directory / "transactions.parquet")
    pq.write_table(players, directory / "business_sample_players.parquet")
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_reproducible_history_grain_and_cash_separation(cohort, tmp_path):
    events, players, manifest = generate(cohort)
    repeated, repeated_players, repeated_manifest = generate(cohort.take(list(reversed(range(cohort.num_rows)))))
    assert events.equals(repeated) and players.equals(repeated_players) and manifest == repeated_manifest
    rows = events.to_pylist()
    assert len({row["transaction_id"] for row in rows}) == len(rows)
    assert len({row["player_id"] for row in players.to_pylist()}) == cohort.num_rows
    assert len({(row["player_id"], row["product_id"]) for row in rows}) < len(rows)
    cash_ids = {row["player_id"] for row in rows if row["currency_id"] in {"USD", "BRL"}}
    nonpayers = set(cohort["player_id"].to_pylist()) - cash_ids
    assert nonpayers
    assert all(any(row["player_id"] == player and row["currency_id"] == "L_BE" for row in rows) for player in nonpayers)
    assert all(row["amount_usd"] is None for row in rows if row["currency_id"] in {"L_RP", "L_BE"})
    assert all(row["amount_usd"] == row["amount_spent"] for row in rows if row["currency_id"] == "USD")
    assert any(row["amount_usd"] != row["amount_spent"] for row in rows if row["currency_id"] == "BRL")
    assert sum((row["amount_usd"] or Decimal(0) for row in rows), Decimal(0)) == Decimal(manifest["cash_spent_usd_alltime"])
    assert manifest["history_start_at"][:10] < manifest["purchase_window_start"]
    write_sample(tmp_path, events, players, manifest)
    validate_files(tmp_path)


def test_loader_rejects_mismatch_before_network_and_only_allows_sample_tables(cohort, tmp_path):
    events, players, manifest = generate(cohort)
    changed = events.to_pylist()
    changed[0]["scenario_id"] = "other-scenario"
    write_sample(tmp_path, pa.Table.from_pylist(changed, schema=TRANSACTION_SCHEMA), players, manifest)
    with patch("load.load_business_sample.get_connection") as connection:
        with pytest.raises(ValueError, match="scenario"):
            load_sample(tmp_path)
        connection.assert_not_called()
    cursor = Mock()
    with pytest.raises(ValueError, match="non-sample"):
        replace_sample_table(cursor, "league_pipeline.raw.players", TRANSACTION_SCHEMA)
    cursor.execute.assert_not_called()
    for name in SAMPLE_TABLES.values():
        replace_sample_table(cursor, name, TRANSACTION_SCHEMA)
    assert all(any(name in call.args[0] for name in SAMPLE_TABLES.values()) for call in cursor.execute.call_args_list)


def test_incomplete_load_and_stale_gold_block_export(cohort):
    _, _, manifest = generate(cohort)
    public = {key: value for key, value in manifest.items() if key not in {
        "base_weights", "weight_offsets", "customer_probabilities", "nonpayer_probabilities"}}
    cursor = Mock()
    cursor.fetchone.return_value = (0, 0, 0, 0, None, None)
    with pytest.raises(ValueError, match="incomplete"):
        warehouse_metadata(cursor)
    raw = (manifest["player_count"], manifest["player_count"], 1, 1, json.dumps(public), manifest["scenario_id"])
    tx = (manifest["transaction_count"], manifest["transaction_count"], 1, manifest["scenario_id"],
          Decimal(manifest["cash_spent_usd_alltime"]), manifest["fiat_transaction_count"])
    stale_gold = (manifest["player_count"], manifest["player_count"], 1, "old-scenario", manifest["transaction_count"],
                  Decimal(manifest["cash_spent_usd_alltime"]), manifest["fiat_transaction_count"])
    cursor.fetchone.side_effect = [raw, tx, stale_gold]
    with pytest.raises(ValueError, match="stale"):
        warehouse_metadata(cursor)
