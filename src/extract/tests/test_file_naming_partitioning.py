import json
import re
from datetime import datetime, timezone

import get_masteries
import get_players
import output_helper
import t_utilities as util

util.set_path_for_extract_modules()

PARTITIONS = [
	("region", "na1"),
	("queue", "RANKED_SOLO_5x5"),
	("tier", "GOLD"),
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
	assert get_players.build_players_filename("I", "153000") == "players_I_153000.json"


def test_build_players_filename_defaults_correctly():
	filename = get_players.build_players_filename("II")
	assert re.fullmatch(r"players_II_\d{6}\.json", filename)


def test_save_players_creates_file_at_expected_partitioned_path(tmp_path):
	players = [{"puuid": "p1", "tier": "GOLD"}, {"puuid": "p2", "tier": "GOLD"}]

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
	expected_path = expected_path / "players_I_153000.json"

	assert output_path == expected_path
	assert output_path.is_file()

	payload = json.loads(output_path.read_text(encoding="utf-8"))
	assert payload["region"] == "na1"
	assert payload["queue"] == "RANKED_SOLO_5x5"
	assert payload["tier"] == "GOLD"
	assert payload["division"] == "I"
	assert payload["patch"] == "15.1"
	assert payload["loose_date"] == "250101"
	assert payload["players"] == players


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

	output_path = get_masteries.save_masteries(mastery_rows, info=info, patch="15.1", output_path=tmp_path)
	assert output_path != None

	expected_path = tmp_path
	for key, value in PARTITIONS:
		expected_path = expected_path / f"{key}={value}"
	expected_path = expected_path / "masteries_I_153000_puuid-1.json"

	assert output_path == expected_path
	assert output_path.is_file()

	payload = json.loads(output_path.read_text(encoding="utf-8"))
	assert payload["puuid"] == "puuid-1"
	assert payload["region"] == "na1"
	assert payload["queue"] == "RANKED_SOLO_5x5"
	assert payload["tier"] == "GOLD"
	assert payload["division"] == "I"
	assert payload["masteries"] == mastery_rows