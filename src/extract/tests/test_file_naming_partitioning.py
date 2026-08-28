import json
from datetime import datetime, timezone
import re
import pyarrow.parquet as pq
import get_masteries
import get_players
import output_helper
import extract.tests.t_utilities as util

util.set_path_for_extract_modules()

PARTITIONS = [
    ("region", "na1"),
    ("queueType", "RANKED_SOLO_5x5"),
    ("tier", "GOLD"),
    ("rank", "I"),
    ("patch", "15.1"),
    ("date", "250101"),
]


def test_get_partitioned_path_builds_expected_nested_structure(tmp_path):
    path = output_helper.get_partitioned_path(tmp_path, PARTITIONS)

    expected = tmp_path
    for key, value in PARTITIONS:
        expected = expected / f"{key}={value}"

    assert path == expected
    assert path.is_dir()


def test_build_players_filename_with_explicit_time():
    assert get_players.build_players_filename("153000") == "players_153000.parquet"


def test_build_players_filename_defaults_correctly():
    filename = get_players.build_players_filename()
    assert re.fullmatch(r"players_\d{6}\.parquet", filename)


def test_save_players_creates_file_at_expected_partitioned_path(tmp_path):
    players = [{"puuid": "p1"}, {"puuid": "p2"}]

    output_path = get_players.save_players(
        players,
        output_path=tmp_path,
        region="na1",
        queue="RANKED_SOLO_5x5",
        tier="GOLD",
        division="I",
        patch="15.1",
        date="250101",
        time="153000",
    )

    expected_path = tmp_path
    for key, value in PARTITIONS:
        expected_path = expected_path / f"{key}={value}"
    expected_path = expected_path / "players_153000.parquet"

    assert output_path == expected_path
    assert output_path.is_file()

    table = pq.read_table(output_path)
    assert table.to_pylist() == players


def test_save_masteries_creates_file_at_expected_partitioned_path(tmp_path):
    logged_at = datetime(2025, 1, 1, 15, 30, 0, tzinfo=timezone.utc)
    info = {
        "region": "na1",
        "queue": "RANKED_SOLO_5x5",
        "tier": "GOLD",
        "division": "I",
        "puuid": "puuid-1",
        "latest_logged_at": logged_at,
    }
    mastery_rows = [{"championId": 1, "championLevel": 5}]

    output_path = get_masteries.save_masteries(
        mastery_rows, info=info, patch="15.1", output_path=tmp_path
    )
    assert output_path != None

    expected_path = tmp_path
    for key, value in PARTITIONS:
        expected_path = expected_path / f"{key}={value}"
    expected_path = expected_path / "masteries_153000_puuid-1.parquet"

    assert output_path == expected_path
    assert output_path.is_file()

    table = pq.read_table(output_path)
    assert table.to_pylist() == mastery_rows
