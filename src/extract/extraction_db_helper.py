"""Helper script to handle all local database operations for the pipeline.
Most operations take an optional conn parameter, mostly for testing with mocked values, but keep in mind that whoever passes it must also handle the connection fully"""

import sqlite3
from datetime import datetime, timezone

from loguru import logger

DB_PATH = "data/database/extraction.db"
OptStr = str | None


def is_active(db_path: str = DB_PATH) -> bool:
    """Check if the database is active and accessible."""
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("SELECT 1")
        return True
    except sqlite3.Error as e:
        logger.error(f"Database connection error: {e}")
        return False
    finally:
        if conn is not None:
            conn.close()


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row
    return conn


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def start_run(pipeline_name: str, conn: sqlite3.Connection | None = None) -> int:
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO runs (pipeline_name, started_at, status) VALUES (?, ?, 'running')",
            (pipeline_name, now()),
        )
        if own_conn:
            conn.commit()
        run_id = cur.lastrowid
    finally:
        if own_conn:
            conn.close()
    int_id = int(run_id or -1)
    if int_id < 0:
        logger.error(f"Failed to start a new run for pipeline {pipeline_name}.")
    return int_id


def heartbeat_run(run_id: int, conn: sqlite3.Connection | None = None):
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        conn.execute("UPDATE runs SET last_heartbeat=? WHERE run_id=?", (now(), run_id))
        if own_conn:
            conn.commit()
    finally:
        if own_conn:
            conn.close()


def finish_run(
    run_id: int,
    status: str,
    error_message: OptStr = None,
    conn: sqlite3.Connection | None = None,
):
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        conn.execute(
            "UPDATE runs SET finished_at=?, status=?, error_message=? WHERE run_id=?",
            (now(), status, error_message, run_id),
        )
        if own_conn:
            conn.commit()
    finally:
        if own_conn:
            conn.close()


def add_player_task(run_id: int, conn: sqlite3.Connection | None = None) -> int:
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        heartbeat_run(run_id, conn)
        cur = conn.execute(
            "INSERT INTO player_tasks (run_id, status) VALUES (?, 'pending')", (run_id,)
        )
        if own_conn:
            conn.commit()
        task_id = cur.lastrowid
    finally:
        if own_conn:
            conn.close()
    int_id = int(task_id or -1)
    if int_id < 0:
        logger.error(f"Failed to add a new player task for run {run_id}.")
    return int_id


def update_player_task(
    task_id: int,
    status: str,
    file_path: OptStr = None,
    error_message: OptStr = None,
    conn: sqlite3.Connection | None = None,
):
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        if status == "in_progress":
            conn.execute(
                "UPDATE player_tasks SET status=?, started_at=?, attempts=attempts+1 WHERE task_id=?",
                (status, now(), task_id),
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
                (status, now(), file_path, error_message, task_id),
            )
        if own_conn:
            conn.commit()
    finally:
        if own_conn:
            conn.close()


def add_player_records(
    player_id: str,
    file_path: str,
    player_task_id: int,
    region: str,
    queue: str,
    tier: str,
    division: str,
    patch: str,
    conn: sqlite3.Connection | None = None,
):
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
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
            (
                player_id,
                player_task_id,
                file_path,
                now(),
                patch,
                region,
                queue,
                tier,
                division,
                player_task_id,
                file_path,
                now(),
                patch,
                region,
                queue,
                tier,
                division,
            ),
        )
        if own_conn:
            conn.commit()
    finally:
        if own_conn:
            conn.close()


def add_mastery_task(
    run_id: int, player_id: str, conn: sqlite3.Connection | None = None
) -> int:
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        heartbeat_run(run_id, conn)
        cur = conn.execute(
            "INSERT INTO mastery_tasks (run_id, player_id, status) VALUES (?, ?, 'pending')",
            (run_id, player_id),
        )
        if own_conn:
            conn.commit()
        task_id = cur.lastrowid
    finally:
        if own_conn:
            conn.close()
    int_id = int(task_id or -1)
    if int_id < 0:
        logger.error(f"Failed to add a new mastery task for player {player_id}.")
    return int_id


def update_mastery_task(
    task_id: int,
    status: str,
    patch: str,
    file_path: OptStr = None,
    error_message: OptStr = None,
    conn: sqlite3.Connection | None = None,
):
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        if status == "in_progress":
            row = conn.execute(
                """
				UPDATE mastery_tasks
				SET status=?, started_at=?, attempts=attempts+1
				WHERE task_id=?
				RETURNING player_id
				""",
                (status, now(), task_id),
            ).fetchone()
        else:  # success or failed
            row = conn.execute(
                """
				UPDATE mastery_tasks
				SET status=?,
					finished_at=?,
					file_path=?,
					error_message=?
				WHERE task_id=?
				RETURNING player_id
				""",
                (status, now(), file_path, error_message, task_id),
            ).fetchone()

        if row is None:
            logger.error(f"No mastery task found with task_id {task_id}.")
            return

        update_player_records(
            status, file_path, row["player_id"], patch, conn, mastery_task_id=task_id
        )
        if own_conn:
            conn.commit()
    finally:
        if own_conn:
            conn.close()


def update_player_records(
    status: str,
    file_path: OptStr,
    player_id: str,
    patch: str,
    conn: sqlite3.Connection,
    mastery_task_id: int | None = None,
):
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
        (status, file_path, mastery_task_id, now(), patch, player_id),
    )


def get_mastery_id_from_list(
    task_ids: list[int], puuid: str, conn: sqlite3.Connection | None = None
) -> int:
    """
    Given a list of task_ids and a puuid, return the task_id that matches the puuid.
    \nIf no match is found, return None.
    """
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT task_id FROM mastery_tasks WHERE task_id IN ({seq}) AND player_id=?".format(
                seq=",".join(["?"] * len(task_ids))
            ),
            (*task_ids, puuid),
        )
        result = cur.fetchone()
    finally:
        if own_conn:
            conn.close()
    int_id = int(result["task_id"] or -1) if result else -1
    if int_id < 0:
        logger.error(f"No task ID found for player {puuid} in the provided task list.")
    return int_id


def cleanup_stale_runs(conn: sqlite3.Connection | None = None):
    """
    Clean up potential stalled runs. Fully clearing related tasks and records.
    \nChecks if a run's heartbeat has been longer than an hour.
    """
    conn_supplied = conn
    if not conn_supplied:
        conn = get_connection()
    try:
        cur = conn.execute(
            """
			UPDATE runs
			SET status = 'failed',
				finished_at = ?,
				error_message = 'Run stalled or silent cancelled'
			WHERE status = 'running' AND datetime(last_heartbeat) < datetime('now', '-1 hour')
			RETURNING run_id
			""",
            (now(),),
        )
        stalled_run_ids = [row["run_id"] for row in cur.fetchall()]

        logger.info(f"Found {len(stalled_run_ids)} stalled runs to clean up.")
        for run in stalled_run_ids:
            cleanup_failed_run(run, conn)

        if not conn_supplied:
            conn.commit()
    finally:
        if not conn_supplied:
            conn.close()


def cleanup_failed_run(run_id: int, conn: sqlite3.Connection | None = None):
    """
    Clear the tasks and associated player records of a failed run.
    """
    conn_supplied = conn
    if not conn_supplied:
        conn = get_connection()
    try:
        logger.info(f"Cleaning up failed run {run_id}.")
        failed_player_tasks = conn.execute(
            "SELECT task_id FROM player_tasks WHERE run_id = ? AND status != 'success'",
            (run_id,),
        ).fetchall()
        failed_mastery_tasks = conn.execute(
            "SELECT task_id FROM mastery_tasks WHERE run_id = ? AND status != 'success'",
            (run_id,),
        ).fetchall()
        failed_player_task_ids = [row["task_id"] for row in failed_player_tasks]
        failed_mastery_task_ids = [row["task_id"] for row in failed_mastery_tasks]

        if failed_player_task_ids:
            conn.execute(
                """
				DELETE FROM players_recorded
				WHERE json_array_length(player_task_ids) = 1
				AND json_extract(player_task_ids, '$[0]') IN ({seq})
				""".format(seq=",".join(["?"] * len(failed_player_task_ids))),
                tuple(failed_player_task_ids),
            )

        if failed_mastery_task_ids:
            conn.execute(
                """
				UPDATE players_recorded
				SET mastery_status='failed'
				WHERE mastery_task_id IN ({seq})
				""".format(seq=",".join(["?"] * len(failed_mastery_task_ids))),
                tuple(failed_mastery_task_ids),
            )

        conn.execute(
            """
			UPDATE player_tasks
			SET status='failed', finished_at=?, error_message='Run failed or cancelled'
			WHERE run_id = ? AND status != 'success'
			""",
            (now(), run_id),
        )
        conn.execute(
            """
			UPDATE mastery_tasks
			SET status='failed', finished_at=?, error_message='Run failed or cancelled'
			WHERE run_id = ? AND status != 'success'
			""",
            (now(), run_id),
        )
        if not conn_supplied:
            conn.commit()
    finally:
        if not conn_supplied:
            conn.close()


def claim_players_missing_masteries(
    include_stale_success: bool = False,
    limit: int | None = None,
    conn: sqlite3.Connection | None = None,
    claim: bool = True,
) -> list[str]:
    """
    Get list of player IDs (puuids) with mastery_status 'failed' or 'pending'.
    \nIf include_stale_success is True, also include players with 'success' status that:
    \n- Have mastery logged at least 1 week old
    \n- AND the last logged player was added in the last 24 hours
    """
    own_conn = conn is None
    status = "in_progress" if claim else "pending"
    if own_conn:
        conn = get_connection()
    try:
        cur = conn.execute(
            """
		UPDATE players_recorded 
		SET mastery_status=? 
		WHERE player_id IN (
			SELECT player_id 
			FROM players_recorded 
			WHERE mastery_status 
			IN ('failed', 'pending') 
			LIMIT ?) 
		RETURNING player_id
		""",
            (status, limit if limit is not None else 1000000),
        )
        players_found = cur.fetchall()
        if include_stale_success:
            cur_stale = conn.execute(
                """
				UPDATE players_recorded
				SET mastery_status=?
				WHERE player_id IN (
					SELECT player_id
					FROM players_recorded
					WHERE json_array_length(paths_logged_at) > 0
					AND datetime(json_extract(paths_logged_at, '$[' || (json_array_length(paths_logged_at) - 1) || ']')) > datetime('now', '-24 hours')
					AND datetime(mastery_logged_at) < datetime('now', '-7 days')
					AND mastery_status = 'success'
					LIMIT ?
				)
				RETURNING player_id
				""",
                (status, limit if limit is not None else 1000000),
            )
            players_found += cur_stale.fetchall()
        players = [row["player_id"] for row in players_found]
        if own_conn:
            conn.commit()
    finally:
        if own_conn:
            conn.close()
    if limit is not None:
        players = players[:limit]
    return players


def get_mastery_status_for_player(
    player_id: str, conn: sqlite3.Connection | None = None
) -> str:
    """
    Get the mastery status for a given player ID (puuid).
    \nReturns 'pending', 'in_progress', 'success', or 'failed'.
    """
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT mastery_status FROM players_recorded WHERE player_id = ?",
            (player_id,),
        )
        result = cur.fetchone()
    finally:
        if own_conn:
            conn.close()
    return str(result["mastery_status"] if result else None)


def get_player_info(
    player_id: str, conn: sqlite3.Connection | None = None
) -> dict | None:
    """
    Get the player info for a given player ID (puuid).
    \nReturns a dictionary with keys: region, queue, tier, division, latest log time.
    """
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT region, queue, tier, division, json_extract(paths_logged_at, '$[' || (json_array_length(paths_logged_at) - 1) || ']') as latest_logged_at FROM players_recorded WHERE player_id = ?",
            (player_id,),
        )
        result = cur.fetchone()
    finally:
        if own_conn:
            conn.close()
    if result:
        data = dict(result)
        data["puuid"] = player_id
        if data["latest_logged_at"]:
            data["latest_logged_at"] = datetime.fromisoformat(data["latest_logged_at"])
        return data
    return None


def get_players_in_timespan(
    days_ago: int,
    region: OptStr = None,
    queue: OptStr = None,
    tier: OptStr = None,
    division: OptStr = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict]:
    """
    Get all players for a given timespan (in days), with optional region, queue, tier, and division parameters.
    \nReturns a list of player strings.
    """
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        query = """
			SELECT player_id
			FROM players_recorded
			WHERE datetime(json_extract(paths_logged_at, '$[' || (json_array_length(paths_logged_at) - 1) || ']')) > datetime('now', ?)
		"""
        params = [f"-{days_ago} days"]

        filters = []
        for column, value in (
            ("region", region),
            ("queue", queue),
            ("tier", tier),
            ("division", division),
        ):
            if value not in (None, ""):
                filters.append(f"{column} = ?")
                params.append(value)

        if filters:
            query += " AND " + " AND ".join(filters)

        cur = conn.execute(query, params)
        players = [row["player_id"] for row in cur.fetchall()]
    finally:
        if own_conn:
            conn.close()
    return players


def get_players_in_patch(
    patch: str,
    region: OptStr = None,
    queue: OptStr = None,
    tier: OptStr = None,
    division: OptStr = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict]:
    """
    Get all players for a given patch, with optional region, queue, tier, and division parameters.
    \nReturns a list of player dictionaries.
    \nOnly considers players with masteries logged for that patch. Meaning running an operation on a patch that has no masteries logged will return an empty list.
    """
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        query = """
			SELECT player_id
			FROM players_recorded
			WHERE mastery_patch = ?
		"""
        params = [patch]

        filters = []
        for column, value in (
            ("region", region),
            ("queue", queue),
            ("tier", tier),
            ("division", division),
        ):
            if value not in (None, ""):
                filters.append(f"{column} = ?")
                params.append(value)

        if filters:
            query += " AND " + " AND ".join(filters)

        cur = conn.execute(query, params)
        players = [row["player_id"] for row in cur.fetchall()]
    finally:
        if own_conn:
            conn.close()
    return players


def get_page_info(
    region: str,
    queue: str,
    patch: str,
    tiers: list[str] | tuple[str, ...],
    divisions: list[str] | tuple[str, ...],
    conn: sqlite3.Connection | None = None,
) -> dict[tuple[str, str], tuple[int, int]]:
    """
    Returns a dictionary of (tier, division) -> (loop_count, players_in_division) for the given region, queue, patch, tiers, and divisions.
    \nMissing tiers or divisions will return an empty dictionary.
    \nMissing rows are treated as zeroed defaults so the selector can still pick a candidate.
    """
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        stats: dict[tuple[str, str], tuple[int, int]] = {}

        if not tiers or not divisions:
            return stats

        for tier in tiers:
            for division in divisions:
                stats[(tier, division)] = (0, 0)

        tier_placeholders = ",".join(["?"] * len(tiers))
        division_placeholders = ",".join(["?"] * len(divisions))

        loop_rows = conn.execute(
            f"""
			SELECT tier, division, loop_count
			FROM tier_division_pages
			WHERE region = ? AND queue = ? AND patch = ?
			AND tier IN ({tier_placeholders}) AND division IN ({division_placeholders})
			""",
            (region, queue, patch, *tiers, *divisions),
        ).fetchall()
        loop_counts = {
            (row["tier"], row["division"]): int(row["loop_count"]) for row in loop_rows
        }

        count_rows = conn.execute(
            f"""
			SELECT tier, division, COUNT(*) AS division_player_count
			FROM players_recorded
			WHERE region = ? AND queue = ? AND mastery_patch = ?
			AND tier IN ({tier_placeholders}) AND division IN ({division_placeholders})
			GROUP BY tier, division
			""",
            (region, queue, patch, *tiers, *divisions),
        ).fetchall()
        player_counts = {
            (row["tier"], row["division"]): int(row["division_player_count"])
            for row in count_rows
        }

        for key in stats:
            stats[key] = (loop_counts.get(key, 0), player_counts.get(key, 0))

        return stats
    finally:
        if own_conn:
            conn.close()


def get_page_and_loop(
    region: str,
    queue: str,
    tier: str,
    division: str,
    patch: str,
    conn: sqlite3.Connection | None = None,
) -> tuple[int, int]:
    """
    Get the current page and loop for a given region, queue, tier, division, and patch.
    \nIf no record exists, create one with page 1 and return it.
    """
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        row = conn.execute(
            """
			INSERT INTO tier_division_pages (
				region, queue, tier, division, patch, current_page,
				loop_count, last_player_count, last_updated_at
			) VALUES (?, ?, ?, ?, ?, 1, 0, 0, ?)
			ON CONFLICT(region, queue, tier, division, patch) DO UPDATE SET
				region = region
			RETURNING current_page, loop_count
			""",
            (region, queue, tier, division, patch, now()),
        ).fetchone()
        if own_conn:
            conn.commit()
        return (int(row["current_page"]), int(row["loop_count"]))
    finally:
        if own_conn:
            conn.close()


def update_page_info(
    region: str,
    queue: str,
    tier: str,
    division: str,
    patch: str,
    player_count: int,
    conn: sqlite3.Connection | None = None,
) -> int:
    """
    Update the page tracking for a given region, queue, tier, division, and patch.

    If the current player count is lower than the previous one, reset page to 1 and increment loop_count.
    Otherwise increment page by 1.

    Returns the updated current_page, or 0 if no record exists.
    """
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        cursor = conn.execute(
            """
			UPDATE tier_division_pages
			SET
				loop_count = CASE
					WHEN ? < last_player_count THEN loop_count + 1
					ELSE loop_count
				END,
				current_page = CASE
					WHEN ? < last_player_count THEN 1
					ELSE current_page + 1
				END,
				last_player_count = ?,
				last_updated_at = ?
			WHERE region = ? AND queue = ? AND tier = ? AND division = ? AND patch = ?
			RETURNING current_page
			""",
            (
                player_count,
                player_count,
                player_count,
                now(),
                region,
                queue,
                tier,
                division,
                patch,
            ),
        )

        row = cursor.fetchone()
        if own_conn:
            conn.commit()
        if row is None:
            logger.warning(
                f"No page info found for {region} {queue} {tier} {division} {patch}."
            )
            return 0
        return int(row["current_page"])
    finally:
        if own_conn:
            conn.close()
