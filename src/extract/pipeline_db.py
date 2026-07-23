"""Helper script to handle all local database operations for the pipeline"""
import sqlite3
from datetime import datetime, timezone
from loguru import logger

DB_PATH = "data/database/pipeline_meta.db"
OptStr = str | None

def is_active(db_path: str = DB_PATH) -> bool:
	"""Check if the database is active and accessible."""
	try:
		conn = sqlite3.connect(db_path)
		conn.execute("SELECT 1")
		conn.close()
		return True
	except sqlite3.Error as e:
		logger.error(f"Database connection error: {e}")
		return False

def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
	conn = sqlite3.connect(db_path)
	conn.execute("PRAGMA journal_mode=WAL;")
	conn.execute("PRAGMA foreign_keys=ON;")
	conn.row_factory = sqlite3.Row
	return conn

def now() -> str:
	return datetime.now(timezone.utc).isoformat()

def start_run(pipeline_name: str) -> int:
	conn = get_connection()
	cur = conn.execute(
		"INSERT INTO runs (pipeline_name, started_at, status) VALUES (?, ?, 'running')",
		(pipeline_name, now())
	)
	conn.commit()
	run_id = cur.lastrowid
	conn.close()
	int_id = int(run_id or -1)
	if int_id < 0:
		logger.error(f"Failed to start a new run for pipeline {pipeline_name}.")
	return int_id


def heartbeat_run(run_id: int):
	conn = get_connection()
	conn.execute(
		"UPDATE runs SET last_heartbeat=? WHERE run_id=?",
		(now(), run_id)
	)
	conn.commit()
	conn.close()


def finish_run(run_id: int, status: str, error_message: OptStr=None):
	conn = get_connection()
	conn.execute(
		"UPDATE runs SET finished_at=?, status=?, error_message=? WHERE run_id=?",
		(now(), status, error_message, run_id)
	)
	conn.commit()
	conn.close()


def add_player_task(run_id: int) -> int:
	conn = get_connection()
	heartbeat_run(run_id)
	cur = conn.execute(
		"INSERT INTO player_tasks (run_id, status) VALUES (?, 'pending')",
		(run_id,)
	)
	conn.commit()
	task_id = cur.lastrowid
	conn.close()
	int_id = int(task_id or -1)
	if int_id < 0:
		logger.error(f"Failed to add a new player task for run {run_id}.")
	return int_id


def update_player_task(task_id: int, status: str, file_path: OptStr=None, error_message: OptStr=None):
	conn = get_connection()
	if status == "in_progress":
		conn.execute(
			"UPDATE player_tasks SET status=?, started_at=?, attempts=attempts+1 WHERE task_id=?",
			(status, now(), task_id)
		)
	else:  # success or failed
		conn.execute(
			"""
			UPDATE player_tasks
			SET status=?,
				finished_at=?,
				file_path=?,
				error_message=?
			WHERE task_id=?
			""",
			(status, now(), file_path, error_message, task_id)
		)
	conn.commit()
	conn.close()

	
def add_player_records(player_id: str, file_path: str, player_task_id: int, region: str, queue: str, tier: str, division: str, patch: str):
	conn = get_connection()
	conn.execute(
		"""
		INSERT INTO players_recorded (player_id, player_task_ids, paths, paths_logged_at, patches_logged, mastery_status, region, queue, tier, division)
		VALUES (?, json_array(?), json_array(?), json_array(?), json_array(?), 'pending', ?, ?, ?, ?)

		ON CONFLICT(player_id) DO UPDATE SET
			player_task_ids = json_insert(player_task_ids, '$[#]', ?),
			paths = json_insert(paths, '$[#]', ?),
			paths_logged_at = json_insert(paths_logged_at, '$[#]', ?),
			patches_logged = json_insert(patches_logged, '$[#]', ?),
			region = ?,
			queue = ?,
			tier = ?,
			division = ?
		""",
		(player_id, player_task_id, file_path, now(), patch, region, queue, tier, division, player_task_id, file_path, now(), patch, region, queue, tier, division)
	)
	conn.commit()
	conn.close()


def add_mastery_task(run_id: int, player_id: str) -> int:
	conn = get_connection()
	heartbeat_run(run_id)
	cur = conn.execute(
		"INSERT INTO mastery_tasks (run_id, player_id, status) VALUES (?, ?, 'pending')",
		(run_id, player_id)
	)
	conn.commit()
	task_id = cur.lastrowid
	conn.close()
	int_id = int(task_id or -1)
	if int_id < 0:
		logger.error(f"Failed to add a new mastery task for player {player_id}.")
	return int_id


def update_mastery_task(task_id: int, status: str, patch: str, file_path: OptStr=None, error_message: OptStr=None):
	conn = get_connection()
	player_id = conn.execute("SELECT player_id FROM mastery_tasks WHERE task_id=?", (task_id,)).fetchone()["player_id"]
	if status == "in_progress":
		conn.execute(
			"UPDATE mastery_tasks SET status=?, started_at=?, attempts=attempts+1 WHERE task_id=?",
			(status, now(), task_id)
		)
	else:  # success or failed
		conn.execute(
			"""
			UPDATE mastery_tasks 
			SET status=?, 
				finished_at=?, 
				file_path=?, 
				error_message=?
			WHERE task_id=?
			""",
			(status, now(), file_path, error_message, task_id)
		)
		
	update_player_records(status, file_path, player_id, patch, conn, mastery_task_id=task_id)
	
	conn.commit()
	conn.close()


def update_player_records(status: str, file_path: OptStr, player_id: str, patch: str, conn: sqlite3.Connection, mastery_task_id: int|None=None):
	conn.execute(
			"""
			UPDATE players_recorded
			SET mastery_status = ?,
				mastery_path = ?,
				mastery_task_id = ?,
				mastery_logged_at = ?,
				mastery_patch = ?
			WHERE player_id = ?
			""",
			(status, file_path, mastery_task_id, now(), patch, player_id)
		)

	
def get_mastery_id_from_list(task_ids: list[int], puuid: str) -> int:
	"""
	Given a list of task_ids and a puuid, return the task_id that matches the puuid.
	\nIf no match is found, return None.
	"""
	conn = get_connection()
	cur = conn.execute(
		"SELECT task_id FROM mastery_tasks WHERE task_id IN ({seq}) AND player_id=?".format(
			seq=','.join(['?'] * len(task_ids))
		),
		(*task_ids, puuid)
	)
	result = cur.fetchone()
	conn.close()
	int_id = int(result["task_id"] or -1) if result else -1
	if int_id < 0:
		logger.error(f"No task ID found for player {puuid} in the provided task list.")
	return int_id


def cleanup_stale_runs():
	"""
	Clean up potential stalled runs. Fully clearing related tasks and records.
	\nChecks if a run's heartbeat has been longer than an hour.
	"""
	conn = get_connection()
	
	# Get list of run IDs where the run stalled for over an hour
	cur = conn.execute(
		"SELECT run_id FROM runs WHERE status = 'running' AND datetime(last_heartbeat) < datetime('now', '-1 hour')"
	)
	stalled_run_ids = [row["run_id"] for row in cur.fetchall()]
	if stalled_run_ids:
		runs_placeholder = ','.join(['?'] * len(stalled_run_ids))
		query = f"""
			UPDATE runs 
			SET status = 'failed', 
				finished_at = ?, 
				error_message = 'Run stalled or silent cancelled' 
			WHERE run_id IN ({runs_placeholder})
		"""
		params = [now()] + stalled_run_ids
		conn.execute(query, params)
			
	logger.info(f"Found {len(stalled_run_ids)} stalled runs to clean up.")
	for run in stalled_run_ids:
		cleanup_failed_run(run, conn)

	conn.commit()
	conn.close()


def cleanup_failed_run(run_id: int, conn: sqlite3.Connection|None = None):
	"""
	Clear the tasks and associated player records of a failed run.
	"""
	conn_supplied = conn
	if not conn_supplied:
		conn = get_connection()
	logger.info(f"Cleaning up failed run {run_id}.")
	failed_player_tasks = conn.execute("SELECT task_id FROM player_tasks WHERE run_id = ? AND status != 'success'", (run_id,)).fetchall()
	failed_mastery_tasks = conn.execute("SELECT task_id FROM mastery_tasks WHERE run_id = ? AND status != 'success'", (run_id,)).fetchall()
	failed_player_task_ids = [row["task_id"] for row in failed_player_tasks]
	failed_mastery_task_ids = [row["task_id"] for row in failed_mastery_tasks]
	
	if failed_player_task_ids:
		conn.execute(
			"""
			DELETE FROM players_recorded
			WHERE json_array_length(player_task_ids) = 1
			AND json_extract(player_task_ids, '$[0]') IN ({seq})
			""".format(seq=','.join(['?'] * len(failed_player_task_ids))),
			tuple(failed_player_task_ids)
		)
	
	if failed_mastery_task_ids:
		conn.execute(
			"""
			UPDATE players_recorded
			SET mastery_status='failed'
			WHERE mastery_task_id IN ({seq})
			""".format(seq=','.join(['?'] * len(failed_mastery_task_ids))),
			tuple(failed_mastery_task_ids)
		)
	
	conn.execute(
		"""
		UPDATE player_tasks
		SET status='failed', finished_at=?, error_message='Run failed or cancelled'
		WHERE run_id = ? AND status != 'success'
		""",
		(now(), run_id)
	)
	conn.execute(
		"""
		UPDATE mastery_tasks
		SET status='failed', finished_at=?, error_message='Run failed or cancelled'
		WHERE run_id = ? AND status != 'success'
		""",
		(now(), run_id)
	)
	if not conn_supplied:
		conn.commit()
		conn.close()


def get_players_missing_masteries(include_stale_success: bool=False, limit: int|None=None) -> list[str]:
	"""
	Get list of player IDs (puuids) with mastery_status 'failed' or 'pending'.
	\nIf include_stale_success is True, also include players with 'success' status that:
	\n- Have mastery logged at least 1 week old
	\n- AND the last logged player was added in the last 24 hours
	"""
	conn = get_connection()
	
	if not include_stale_success:
		cur = conn.execute(
			"SELECT player_id FROM players_recorded WHERE mastery_status IN ('failed', 'pending')"
		)
	else:
		cur = conn.execute(
			"""
			SELECT player_id FROM players_recorded
			WHERE datetime(json_extract(paths_logged_at, '$[' || (json_array_length(paths_logged_at) - 1) || ']')) 
				> datetime('now', '-24 hours')
			AND json_array_length(paths_logged_at) > 0
			AND (datetime(mastery_logged_at) < datetime('now', '-7 days') OR mastery_logged_at IS NULL)
			AND mastery_status != 'in_progress'
			"""
		)
	
	players = [row["player_id"] for row in cur.fetchall()]
	if limit is not None:
		players = players[:limit]
	conn.close()
	return players


def get_mastery_status_for_player(player_id: str) -> str:
	"""
	Get the mastery status for a given player ID (puuid).
	\nReturns 'pending', 'in_progress', 'success', or 'failed'.
	"""
	conn = get_connection()
	cur = conn.execute(
		"SELECT mastery_status FROM players_recorded WHERE player_id = ?",
		(player_id,)
	)
	result = cur.fetchone()
	conn.close()
	return str(result["mastery_status"] if result else None)


def get_player_info(player_id: str) -> dict|None:
	"""
	Get the player info for a given player ID (puuid).
	\nReturns a dictionary with keys: region, queue, tier, division, latest log time.
	"""
	conn = get_connection()
	cur = conn.execute(
		"SELECT region, queue, tier, division, json_extract(paths_logged_at, '$[' || (json_array_length(paths_logged_at) - 1) || ']') as latest_logged_at FROM players_recorded WHERE player_id = ?",
		(player_id,)
	)
	
	result = cur.fetchone()
	conn.close()
	if result:
		data = dict(result)
		data["puuid"] = player_id
		if data["latest_logged_at"]:
			data["latest_logged_at"] = datetime.fromisoformat(data["latest_logged_at"])
		return data
	return None


def get_players_in_timespan(days_ago: int, region: OptStr=None, queue: OptStr=None, tier: OptStr=None, division: OptStr=None) -> list[dict]:
	"""
	Get all players for a given timespan (in days), with optional region, queue, tier, and division parameters.
	\nReturns a list of player strings.
	"""
	conn = get_connection()

	query = """
		SELECT player_id
		FROM players_recorded
		WHERE datetime(json_extract(paths_logged_at, '$[' || (json_array_length(paths_logged_at) - 1) || ']')) > datetime('now', ?)
	"""
	params = [f'-{days_ago} days']

	filters = []
	for column, value in (("region", region), ("queue", queue), ("tier", tier), ("division", division)):
		if value not in (None, ""):
			filters.append(f"{column} = ?")
			params.append(value)

	if filters:
		query += " AND " + " AND ".join(filters)

	cur = conn.execute(query, params)
	players = [row["player_id"] for row in cur.fetchall()]
	conn.close()
	return players


def get_players_in_patch(patch: str, region: OptStr=None, queue: OptStr=None, tier: OptStr=None, division: OptStr=None) -> list[dict]:
	"""
	Get all players for a given patch, with optional region, queue, tier, and division parameters.
	\nReturns a list of player dictionaries.
	\nOnly considers players with masteries logged for that patch. Meaning running an operation on a patch that has no masteries logged will return an empty list.
	"""
	conn = get_connection()

	query = """
		SELECT player_id
		FROM players_recorded
		WHERE mastery_patch = ?
	"""
	params = [patch]

	filters = []
	for column, value in (("region", region), ("queue", queue), ("tier", tier), ("division", division)):
		if value not in (None, ""):
			filters.append(f"{column} = ?")
			params.append(value)

	if filters:
		query += " AND " + " AND ".join(filters)

	cur = conn.execute(query, params)
	players = [row["player_id"] for row in cur.fetchall()]
	conn.close()
	return players


def get_page_info(region: str, queue: str, patch: str, tiers: list[str] | tuple[str, ...], divisions: list[str] | tuple[str, ...]) -> dict[tuple[str, str], tuple[int, int]]:
	"""
	Returns a dictionary of (tier, division) -> (loop_count, players_in_division) for the given region, queue, patch, tiers, and divisions.
	\nMissing tiers or divisions will return an empty dictionary.
	\nMissing rows are treated as zeroed defaults so the selector can still pick a candidate.
	"""
	conn = get_connection()
	stats: dict[tuple[str, str], tuple[int, int]] = {}

	if not tiers or not divisions:
		conn.close()
		return stats

	for tier in tiers:
		for division in divisions:
			stats[(tier, division)] = (0, 0)

	tier_placeholders = ",".join(["?"] * len(tiers))
	division_placeholders = ",".join(["?"] * len(divisions))
	query = f"""
		SELECT tier, division, loop_count
		FROM tier_division_pages
		WHERE region = ?
		AND queue = ?
		AND patch = ?
		AND tier IN ({tier_placeholders})
		AND division IN ({division_placeholders})
	"""
	rows = conn.execute(query, (region, queue, patch, *tiers, *divisions)).fetchall()
	
	for row in rows:
		player_count_row = conn.execute( # looping queries is inefficient but it will never go beyond 28 queries, so it works perfectly to give this method more autonomy. the alternative could be storing that info on the database but this is a better tradeoff.
			"""
			SELECT COUNT(*) AS division_player_count
			FROM players_recorded
			WHERE region = ? AND queue = ? AND tier = ? AND division = ? AND mastery_patch = ?
			""",
			(region, queue, row["tier"], row["division"], patch),
		).fetchone()
		player_count = int(player_count_row["division_player_count"]) if player_count_row else 0
		stats[(row["tier"], row["division"])] = (int(row["loop_count"]), player_count)

	conn.close()
	return stats


def get_page_and_loop(region: str, queue: str, tier: str, division: str, patch: str) -> tuple[int, int]:
	"""
	Get the current page and loop for a given region, queue, tier, division, and patch.
	\nIf no record exists, create one with page 1 and return it.
	"""
	conn = get_connection()
	row = conn.execute(
		"""
		SELECT current_page, loop_count
		FROM tier_division_pages
		WHERE region = ? AND queue = ? AND tier = ? AND division = ? AND patch = ?
		""",
		(region, queue, tier, division, patch),
	).fetchone()

	if row is None:
		conn.execute(
			"""
			INSERT INTO tier_division_pages (
				region, queue, tier, division, patch, current_page,
				last_player_count, last_updated_at
			) VALUES (?, ?, ?, ?, ?, 1, 0, ?)
			""",
			(region, queue, tier, division, patch, now()),
		)
		conn.commit()
		conn.close()
		return (1, 0)  # page 1 and loop 0

	conn.close()
	return (int(row["current_page"]), int(row["loop_count"]))

def update_page_info(region: str, queue: str, tier: str, division: str, patch: str, player_count: int):
	"""
	Update the page tracking for a given region, queue, tier, division, and patch.
	\nIf the current player count is lower than the previous one, reset the page to 1.
	\nOtherwise increment the page by 1.
	\nReturns the resulting page number, if no record exists, log a warning and returns 0.
	"""
	conn = get_connection()
	row = conn.execute(
		"""
		SELECT current_page, last_player_count, loop_count
		FROM tier_division_pages
		WHERE region = ? AND queue = ? AND tier = ? AND division = ? AND patch = ?
		""",
		(region, queue, tier, division, patch),
	).fetchone()

	if row is None:
		logger.warning(f"No page info found for {region} {queue} {tier} {division} {patch}.")
		conn.close()
		return 0

	current_page = int(row["current_page"])
	last_player_count = int(row["last_player_count"])
	loop_count = int(row["loop_count"])

	if player_count < last_player_count:
		current_page = 1
		loop_count += 1
	else:
		current_page += 1

	conn.execute(
		"""
		UPDATE tier_division_pages
		SET current_page = ?,
			last_player_count = ?,
			last_updated_at = ?,
			loop_count = ?
		WHERE region = ? AND queue = ? AND tier = ? AND division = ? AND patch = ?
		""",
		(current_page, player_count, now(), loop_count, region, queue, tier, division, patch),
	)
	conn.commit()
	conn.close()

if __name__ == "__main__":
	cleanup_stale_runs()
