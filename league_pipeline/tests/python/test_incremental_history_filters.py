"""Exercise the existing Silver source filters offline, without a warehouse."""

import sqlite3
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import Environment, StrictUndefined

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS = [
    "models/silver/players/dim_players_history.sql",
    "models/silver/masteries/fct_masteries_history.sql",
]


def source_query(model, incremental):
    variables = {"late_arrival_lookback_days": 5, "mastery_freshness_days": 2, "ranked_queue": "solo"}
    environment = Environment(undefined=StrictUndefined)
    environment.globals.update(
        config=lambda **kwargs: "",
        ref=lambda name: name,
        var=variables.__getitem__,
        is_incremental=lambda: incremental,
        this="existing_history",
        dbt_utils=SimpleNamespace(
            safe_divide=lambda numerator, denominator: f"1.0 * {numerator} / nullif({denominator}, 0)",
            generate_surrogate_key=lambda columns: "'unused_key'",
        ),
    )
    rendered = environment.from_string((PROJECT_ROOT / model).read_text(encoding="utf-8")).render()
    # Test source eligibility; deduplication and final surrogate keys are unchanged.
    query = rendered.split("    qualify row_number()", 1)[0] + ") select snapshot_date from source"
    return query.replace("datediff(DAY,", "datediff('DAY',")


@pytest.fixture
def history_database():
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.create_function(
            "to_date", 2,
            lambda value, source_format: date.fromisoformat(f"20{value[:2]}-{value[2:4]}-{value[4:]}").isoformat(),
        )
        connection.create_function(
            "date_sub", 2,
            lambda value, days: (date.fromisoformat(value) - timedelta(days=days)).isoformat() if value else None,
        )
        connection.create_function(
            "datediff", 3, lambda unit, start, end: (date.fromisoformat(end) - date.fromisoformat(start)).days,
        )
        connection.create_function("timestamp_millis", 1, lambda value: value)
        connection.executescript("""
            create table existing_history(snapshot_date text);
            create table dim_players_history(puuid text);
            insert into dim_players_history values ('p');
            create table dim_champions(key integer);
            insert into dim_champions values (1);
            create table bronze_players(
                puuid text, region text, queueType text, tier text, rank text,
                leaguePoints integer, patch text, date text, wins integer, losses integer, _ingested_at integer
            );
            create table bronze_masteries(
                puuid text, championId integer, date text, championPoints integer,
                lastPlayTime integer, _ingested_at integer, patch text
            );
        """)
        for snapshot in ("261004", "261005", "261010", "261012"):
            connection.execute(
                "insert into bronze_players values ('p', 'na1', 'solo', 'GOLD', 'I', 10, '1', ?, 10, 5, 1)",
                (snapshot,),
            )
            connection.execute("insert into bronze_masteries values ('p', 1, ?, 100, 0, 1, '1')", (snapshot,))
        yield connection


@pytest.mark.parametrize("model", MODELS)
def test_empty_incremental_history_accepts_initial_observations(history_database, model):
    query = source_query(model, incremental=True)
    observed = {row[0] for row in history_database.execute(query)}
    assert observed == {"2026-10-04", "2026-10-05", "2026-10-10", "2026-10-12"}


@pytest.mark.parametrize("model", MODELS)
def test_nonempty_incremental_history_keeps_inclusive_lookback(history_database, model):
    history_database.execute("insert into existing_history values ('2026-10-10')")
    query = source_query(model, incremental=True)
    observed = {row[0] for row in history_database.execute(query)}
    assert observed == {"2026-10-05", "2026-10-10", "2026-10-12"}


@pytest.mark.parametrize("model", MODELS)
def test_full_refresh_keeps_all_source_observations(history_database, model):
    history_database.execute("insert into existing_history values ('2026-10-10')")
    query = source_query(model, incremental=False)
    observed = {row[0] for row in history_database.execute(query)}
    assert observed == {"2026-10-04", "2026-10-05", "2026-10-10", "2026-10-12"}
