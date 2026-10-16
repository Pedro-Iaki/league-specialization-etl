"""Freeze every complete core profile at one as-of date, then generate fictional history."""
from __future__ import annotations

import argparse
import calendar
import json
import math
import random
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from functools import partial
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .contract import (
    COHORT_SCHEMA,
    OPTIONAL_REAL_FEATURES,
    PLAYER_SCHEMA,
    REQUIRED_REAL_FEATURES,
    SAMPLE_DIR,
    TRANSACTION_SCHEMA,
    fingerprint,
    read_seeds,
)
from .scenario import BASE_WEIGHTS, CONTROL_BOUNDS, CUSTOMER_PROBABILITIES, GENERATOR_VERSION, WEIGHT_OFFSETS

DEFAULT_QUEUE = "RANKED_SOLO_5x5"  # matches dbt's ranked_queue; --queue can override it
NONPAYER_PROBABILITIES = {"sardine": 0.32, "dolphin": 0.06, "whale": 0.01}
# Map canonical Gold names into the fixed raw cohort contract to preserve scenario fingerprints.
PROFILE_SOURCE_COLUMNS = {
    "active_playstyle": "recent_playstyle",
    "active_primary_champion_key": "recent_primary_champion_key",
    "active_primary_champion_name": "recent_primary_champion_name",
    "active_normalized_entropy": "recent_normalized_entropy",
    "active_top1_share": "recent_top1_share",
    "alltime_top1_share": "lifetime_top1_share",
    "total_mastery_points": "lifetime_mastery_points",
    "champions_with_mastery": "lifetime_champion_count",
    "games_per_day_recent": "latest_rank_period_games_per_day",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, help="Reuse an existing private cohort completely offline")
    parser.add_argument("--refresh-cohort", action="store_true", help="Explicitly replace the frozen cohort from Gold")
    parser.add_argument("--output-dir", type=Path, default=SAMPLE_DIR)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--queue", default=DEFAULT_QUEUE)
    args = parser.parse_args()
    if args.cohort and args.refresh_cohort:
        parser.error("--cohort and --refresh-cohort are mutually exclusive")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    frozen = args.cohort or args.output_dir / "cohort.parquet"
    if args.refresh_cohort or not frozen.exists():
        if args.cohort:
            parser.error("--cohort does not exist; offline mode never fetches from the warehouse")
        cohort, source = fetch_cohort(args.queue)
        pq.write_table(cohort, frozen, compression="zstd")
        print(f"Frozen {cohort.num_rows:,} complete real players at one as-of date")
    else:
        cohort = normalize_cohort(pq.read_table(frozen), args.queue)
        source = "reused complete frozen ranked_mastery_share"
    transactions, players, manifest = generate(cohort, args.seed, args.queue)
    manifest["cohort_ranked_share_export"] = source
    for filename, table in (("transactions.parquet", transactions), ("business_sample_players.parquet", players)):
        temporary = args.output_dir / f".{filename}.tmp"
        pq.write_table(table, temporary, compression="zstd")
        temporary.replace(args.output_dir / filename)
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"{manifest['scenario_id']}: {players.num_rows:,} players, {transactions.num_rows:,} transactions, "
          f"USD {manifest['cash_spent_usd_alltime']} hypothetical source cash")


def fetch_cohort(queue: str) -> tuple[pa.Table, str]:
    from load.databricks_helper import get_connection

    with get_connection() as connection, connection.cursor() as cursor:
        share_available = False
        try:
            cursor.execute("describe table league_pipeline.gold.mart_player_rank_periods")
            share_available = "estimated_ranked_mastery_share" in {row[0] for row in cursor.fetchall()}
        except Exception as error:
            if "TABLE_OR_VIEW_NOT_FOUND" not in str(error):
                raise
        share_cte = """
            select player_id, percentile(estimated_ranked_mastery_share, 0.5) as ranked_mastery_share
            from league_pipeline.gold.mart_player_rank_periods
            where queue = :queue and is_lp_growth_eligible
              and estimated_ranked_mastery_share between 0 and 1
              and period_bucket_end <= (select max(as_of_date) from selected_profiles)
            group by player_id
        """ if share_available else "select cast(null as string) as player_id, cast(null as double) as ranked_mastery_share"
        columns = ", ".join(
            f"p.`{PROFILE_SOURCE_COLUMNS.get(name, name)}` as `{name}`"
            for name in COHORT_SCHEMA.names if name != "ranked_mastery_share"
        )
        cursor.execute(f"""
            with selected_profiles as (
                select * from league_pipeline.gold.mart_player_profile
                where queue = :queue and as_of_date = (
                    select max(as_of_date) from league_pipeline.gold.mart_player_profile where queue = :queue
                )
            ), ranked_share as ({share_cte})
            select {columns}, r.ranked_mastery_share
            from selected_profiles p left join ranked_share r on p.player_id = r.player_id
            order by sha2(p.player_id, 256), p.player_id
        """, parameters={"queue": queue})
        table = cursor.fetchall_arrow()
    complete = select_complete_cohort(table, queue)
    print(f"Selected {complete.num_rows:,} complete players from {table.num_rows:,} current profiles; "
          f"excluded {table.num_rows - complete.num_rows:,} incomplete/invalid profiles; no row cap")
    return complete, ("median valid observed estimated_ranked_mastery_share by player and queue"
                      if share_available else "unavailable; optional field retained as null")


def generate(cohort: pa.Table, seed: int = 42, queue: str = DEFAULT_QUEUE) -> tuple[pa.Table, pa.Table, dict]:
    cohort = normalize_cohort(cohort, queue)
    currencies, products = read_seeds()
    rows = cohort.to_pylist()
    cohort_hash = fingerprint(rows)
    config = {"base_weights": BASE_WEIGHTS, "weight_offsets": WEIGHT_OFFSETS,
              "customer_probabilities": CUSTOMER_PROBABILITIES, "nonpayer_probabilities": NONPAYER_PROBABILITIES,
              "control_bounds": CONTROL_BOUNDS, "currencies": currencies, "products": products}
    config_hash = fingerprint(config)
    scenario_id = "business-" + fingerprint([GENERATOR_VERSION, seed, cohort_hash, config_hash])[:24]
    as_of = rows[0]["as_of_date"]
    end = datetime.combine(as_of + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    window_start = as_of - timedelta(days=59)
    events, players = [], []
    for row in rows:
        rng = random.Random(int(fingerprint([seed, row["player_id"]]), 16))
        tenure_days = rng.randint(120, 8 * 365)  # latent tenure precedes all purchase generation
        start = end - timedelta(days=tenure_days)
        customer = rng.choices(list(CUSTOMER_PROBABILITIES), weights=list(CUSTOMER_PROBABILITIES.values()))[0]
        controls = player_controls(row, tenure_days, customer, rng)
        mastery_count = row["champions_with_mastery"]
        mastery_anchor = mastery_count if mastery_count is not None else 25
        # Mastery can include rotations; ownership can include unused/rewarded champions.
        owned = round(min(200, max(20, mastery_anchor + controls["owned_champions"] + rng.gauss(0, 8))))
        be_count = round(min(owned, max(3, mastery_anchor * rng.uniform(0.35, 0.65) + rng.uniform(2, 8))))
        player_events = []
        add_event = partial(append_event, player_events, row, controls, rng, scenario_id)

        be_products = [product for product in products.values() if product["category"] == "champion"]
        first = start + timedelta(hours=rng.uniform(0, 48))
        add_event(rng.choice(be_products), first)
        for _ in range(be_count - 1):
            add_event(rng.choice(be_products), first + (end - first) * rng.random())

        cosmetic_products = [product for product in products.values() if product["category"] == "cosmetic"]
        cosmetic_expected = be_count * controls["cosmetic_bias"] / (1 - controls["cosmetic_bias"])
        cosmetic_count = max(0, round(cosmetic_expected * rng.uniform(0.75, 1.25)))
        for _ in range(cosmetic_count):
            add_event(rng.choice(cosmetic_products), first + (end - first) * rng.random())

        if rng.random() >= NONPAYER_PROBABILITIES[customer]:
            months = month_windows(first, end)
            # Frequency chooses purchasing months; consistency spreads them regularly or in clusters.
            active_count = sum(rng.random() < controls["payment_frequency"] for _ in months)
            regular = rng.sample(range(len(months)), active_count) if controls["payment_consistency"] < 0.5 else sorted({
                min(len(months) - 1, int((index + 0.5) * len(months) / active_count))
                for index in range(active_count)
            })
            cash_currency = "BRL" if row["region"].upper().startswith("BR") else "USD"
            cash_products = [product for product in products.values() if product["purchase_currency_id"] == cash_currency]
            for month_index in regular:
                lower, upper = months[month_index]
                # Intensity changes transactions per occasion and package size, separately from frequency.
                count = max(1, round(controls["payment_intensity"] * rng.uniform(0.65, 1.35)))
                fraction = min(0.99, max(0.01, rng.gauss(0.5, 0.30 * (1 - controls["payment_consistency"]))))
                occasion = lower + (upper - lower) * fraction
                for _ in range(count):
                    package_weights = [1.8, max(0.2, controls["payment_intensity"]), max(0.1, controls["payment_intensity"] - 1)]
                    add_event(rng.choices(cash_products, weights=package_weights)[0], occasion)
        events.extend(player_events)
        players.append({**row, "simulated_customer_type": customer, "simulated_owned_champions": owned,
                        "scenario_id": scenario_id, "purchase_window_start": window_start,
                        "purchase_window_end": as_of})
    events.sort(key=lambda event: (event["player_id"], event["occurred_at"], event["transaction_id"]))
    manifest = {
        "scenario_id": scenario_id, "generator_seed": seed, "generator_version": GENERATOR_VERSION,
        "provenance": "Purchase history and spending patterns are synthetic; frozen player metrics are real Riot API data.",
        "source": "league_pipeline.gold.mart_player_profile + mart_player_rank_periods",
        "cohort_fingerprint": cohort_hash, "config_fingerprint": config_hash,
        "min_snapshot_date": min(row["snapshot_date"] for row in rows).isoformat(),
        "max_snapshot_date": max(row["snapshot_date"] for row in rows).isoformat(), "as_of_date": as_of.isoformat(),
        "cohort_policy": "all complete current ranked profiles at one as-of date; no row cap",
        "required_real_features": REQUIRED_REAL_FEATURES,
        "optional_real_features": sorted(OPTIONAL_REAL_FEATURES),
        "observed_optional_feature_counts": {
            name: sum(row[name] is not None for row in rows) for name in sorted(OPTIONAL_REAL_FEATURES)
        },
        "purchase_window_start": window_start.isoformat(), "purchase_window_end": as_of.isoformat(),
        "history_start_at": min(event["occurred_at"] for event in events).isoformat(),
        "history_end_at": max(event["occurred_at"] for event in events).isoformat(),
        "player_count": len(players), "transaction_count": len(events),
        "fiat_transaction_count": sum(currencies[event["currency_id"]]["currency_kind"] == "fiat" for event in events),
        "cash_spent_usd_alltime": str(sum((event["amount_usd"] or Decimal(0) for event in events), Decimal(0))),
        "top1_champion_share_source": "mart_player_profile.recent_top1_share",
        "ranked_share_source": "median valid observed ranked-mastery estimate; null when unobserved; optional for eligibility",
        "queue": queue,
    }
    # The same compact metadata is the cohort table's completion marker, not an operational registry.
    for player in players:
        player["scenario_metadata"] = json.dumps(manifest, sort_keys=True)
    private_manifest = {**manifest, "base_weights": BASE_WEIGHTS, "weight_offsets": WEIGHT_OFFSETS,
                        "customer_probabilities": CUSTOMER_PROBABILITIES, "nonpayer_probabilities": NONPAYER_PROBABILITIES}
    return (pa.Table.from_pylist(events, schema=TRANSACTION_SCHEMA),
            pa.Table.from_pylist(players, schema=PLAYER_SCHEMA), private_manifest)


def select_complete_cohort(table: pa.Table, queue: str = DEFAULT_QUEUE) -> pa.Table:
    table = table.select(COHORT_SCHEMA.names).cast(COHORT_SCHEMA)
    rows = [row for row in table.to_pylist() if cohort_row_error(row, queue) is None]
    return normalize_cohort(pa.Table.from_pylist(rows, schema=COHORT_SCHEMA), queue)


def normalize_cohort(table: pa.Table, queue: str = DEFAULT_QUEUE) -> pa.Table:
    missing = set(COHORT_SCHEMA.names) - set(table.column_names)
    if missing:
        raise ValueError(f"Frozen cohort is missing {sorted(missing)}")
    table = table.select(COHORT_SCHEMA.names).cast(COHORT_SCHEMA)
    rows = table.to_pylist()
    if not rows:
        raise ValueError("The selected cohort is empty")
    ids = [row["player_id"] for row in rows]
    if any(not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("Frozen cohort must have unique non-null player_id values")
    dates = {row["as_of_date"] for row in rows}
    if None in dates or len(dates) != 1:
        raise ValueError("Select one real as_of_date; mixed or missing reference dates are not allowed")
    for row in rows:
        error = cohort_row_error(row, queue)
        if error:
            raise ValueError(error + "; refresh the complete cohort or supply a valid offline cohort")
    return pa.Table.from_pylist(sorted(rows, key=lambda row: row["player_id"]), schema=COHORT_SCHEMA)


def cohort_row_error(row: dict, queue: str) -> str | None:
    missing = [column for column in REQUIRED_REAL_FEATURES if row[column] is None
               or isinstance(row[column], str) and not row[column].strip()]
    if missing:
        return f"Missing required real features: {', '.join(missing)}"
    if row["queue"] != queue:
        return "Player must have the configured ranked queue"
    if row["main_role"] not in {"Top", "Jungle", "Middle", "Bottom", "Support"} \
            or row["active_playstyle"] not in {"specialist", "multispecialist", "versatile", "generalist"}:
        return "Unclassified role or active playstyle"
    if row["tier"] not in {"IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD",
                           "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER"}:
        return "Invalid ranked tier"
    if row["snapshot_date"] > row["as_of_date"]:
        return "Profile snapshot is later than the reference date"
    for column in ("active_top1_share", "active_normalized_entropy", "alltime_top1_share", "ranked_mastery_share"):
        if row[column] is not None and (not math.isfinite(row[column]) or not 0 <= row[column] <= 1):
            return f"Invalid cohort fraction: {column}"
    for column in ("active_primary_champion_key", "champions_with_mastery", "total_mastery_points"):
        if row[column] <= 0:
            return f"Invalid cohort mastery/champion value: {column}"
    if row["games_per_day_recent"] is not None and (
        not math.isfinite(row["games_per_day_recent"]) or row["games_per_day_recent"] < 0
    ):
        return "Invalid recent gameplay activity"
    return None


def player_controls(row: dict, tenure_days: int, customer: str, rng: random.Random) -> dict[str, float]:
    groups = {
        "tier": row["tier"], "main_role": row["main_role"],
        "primary_champion": str(row["active_primary_champion_key"]),
        "active_playstyle": row["active_playstyle"],
        "account_age": "new" if tenure_days < 365 else "veteran" if tenure_days >= 3 * 365 else "established",
        "mastery_sum": band(row["total_mastery_points"], 500_000, 2_000_000),
        "ranked_share": band(row["ranked_mastery_share"], 0.35, 0.75),
        "top1_champion_share": band(row["active_top1_share"], 0.3, 0.7),
        "active_entropy": band(row["active_normalized_entropy"], 0.35, 0.75),
        "customer_type": customer,
    }
    weights = BASE_WEIGHTS.copy()
    for group, bucket in groups.items():
        offsets = WEIGHT_OFFSETS[group].get(bucket, WEIGHT_OFFSETS[group]["default"])
        for control, offset in offsets.items():
            weights[control] += offset
    for control, (lower, upper) in CONTROL_BOUNDS.items():
        # Add residual variation after summing and clamping the configured offsets.
        value = min(upper, max(lower, weights[control]))
        noise = 3 if control == "owned_champions" else 0.22 if control == "payment_intensity" else 0.06
        weights[control] = min(upper, max(lower, rng.gauss(value, noise)))
    return weights


def append_event(player_events: list, row: dict, controls: dict, rng: random.Random,
                 scenario_id: str, product: dict, when: datetime) -> None:
    discount = min(0.8, max(0.01, rng.gauss(controls["discount_mean"], 0.06))) \
        if rng.random() < controls["discount_share"] else 0
    factor = Decimal(str(1 - discount))
    price = product["sample_original_price"]
    amount = (price * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    usd = product["sample_amount_usd"]
    usd = (usd * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if usd is not None else None
    sequence = len(player_events)
    player_events.append({
        "transaction_id": fingerprint([scenario_id, row["player_id"], sequence])[:40],
        "player_id": row["player_id"], "product_id": product["product_id"],
        "region_at_purchase": row["region"], "currency_id": product["purchase_currency_id"],
        "original_price": price, "amount_spent": amount, "amount_usd": usd,
        "occurred_at": when.replace(microsecond=0), "scenario_id": scenario_id,
    })


def month_windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    windows = []
    current = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while current < end:
        following = (current + timedelta(days=calendar.monthrange(current.year, current.month)[1]))
        windows.append((max(start, current), min(end, following)))
        current = following
    return windows


def band(value: float | None, low: float, high: float) -> str:
    if value is None:
        return "default"
    return "low" if value < low else "high" if value >= high else "medium"


if __name__ == "__main__":
    main()
