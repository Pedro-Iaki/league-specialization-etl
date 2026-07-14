# pipeline_db.py
import sqlite3
from datetime import datetime, timezone

DB_PATH = "data/database/pipeline_meta.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
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
    return run_id

def heartbeat_run(run_id: int):
    conn = get_connection()
    conn.execute(
    	"UPDATE runs SET last_heartbeat=? WHERE run_id=?",
    	(now(), run_id)
    )
    conn.commit()
    conn.close()


def finish_run(run_id: int, status: str, error_message: str=None):
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
    return task_id


def update_player_task(task_id: int, status: str, file_path: str=None, error_message: str=None):
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

    
def add_player_records(player_id: str, file_path: str, player_task_id: int, region: str, queue: str, tier: str, division: str):
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO players_recorded (player_id, player_task_ids, paths, paths_logged_at, mastery_status, region, queue, tier, division)
        VALUES (?, json_array(?), json_array(?), json_array(?), 'pending', ?, ?, ?, ?)

        ON CONFLICT(player_id) DO UPDATE SET
            player_task_ids = json_insert(player_task_ids, '$[#]', ?),
            paths = json_insert(paths, '$[#]', ?),
            paths_logged_at = json_insert(paths_logged_at, '$[#]', ?)
        """,
        (player_id, player_task_id, file_path, now(), region, queue, tier, division, player_task_id, file_path, now())
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
    return task_id


def update_mastery_task(task_id: int, status: str, file_path: str=None, error_message: str=None):
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
        
    update_player_records(status, file_path, player_id, conn, mastery_task_id=task_id)
    
    conn.commit()
    conn.close()


def update_player_records(status: str, file_path: str, player_id: str, conn, mastery_task_id: int=None):
    conn.execute(
            """
            UPDATE players_recorded
            SET mastery_status = ?,
                mastery_path = ?,
                mastery_task_id = ?,
                mastery_logged_at = ?
            WHERE player_id = ?
            """,
            (status, file_path, mastery_task_id, now(), player_id)
        )
    
def get_mastery_id_from_list(task_ids: list[int], puuid: str) -> int:
    """
    Given a list of task_ids and a puuid, return the task_id that matches the puuid.
    If no match is found, return None.
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
    return result["task_id"] if result else None


def cleanup_stale_runs():
    """
    Clean up potential stalled runs. Fully clearing related tasks and records.
    Checks if a run's heartbeat has been longer than an hour.
    """
    conn = get_connection()
    
    # Get list of run IDs where the run stalled for over an hour
    cur = conn.execute(
        "SELECT run_id FROM runs WHERE status == 'running' AND datetime(last_heartbeat) < datetime('now', '-1 hour')"
    )
    stalled_run_ids = [row["run_id"] for row in cur.fetchall()]
    for run in stalled_run_ids:
        cleanup_failed_run(run)

    conn.commit()
    conn.close()

def cleanup_failed_run(run_id: int):
    """
    Clear the tasks and associated player records of a failed run.
    """
    conn = get_connection()
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
		SET status='failed', finished_at=?, error_message='Run failed'
		WHERE run_id = ? AND status != 'success'
		""",
		(now(), run_id)
	)
    conn.execute(
		"""
		UPDATE mastery_tasks
		SET status='failed', finished_at=?, error_message='Run failed'
		WHERE run_id = ? AND status != 'success'
		""",
		(now(), run_id)
	)
    conn.commit()
    conn.close()

def get_players_missing_masteries(include_stale_success: bool=False, limit: int = None) -> list[str]:
    """
    Get list of player IDs (puuids) with mastery_status 'failed' or 'pending'.
    If include_stale_success is True, also include players with 'success' status that:
    - Have mastery logged at least 1 week old
    - AND the last logged player was added in the last 24 hours
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
    Returns 'pending', 'in_progress', 'success', or 'failed'.
    """
    conn = get_connection()
    cur = conn.execute(
    	"SELECT mastery_status FROM players_recorded WHERE player_id = ?",
    	(player_id,)
    )
    result = cur.fetchone()
    conn.close()
    return result["mastery_status"] if result else None

def get_player_info(player_id: str) -> dict:
    """
    Get the player info for a given player ID (puuid).
    Returns a dictionary with keys: region, queue, tier, division, latest log time.
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
        if data["latest_logged_at"]:
            data["latest_logged_at"] = datetime.fromisoformat(data["latest_logged_at"])
        return data
    return None

def get_players_in_timespan(region: str, queue: str, tier: str, division: str, days_ago: int) -> list[dict]:
    """
    Get all players for a given region, queue, tier, and division within a specified timespan.
    Returns a list of player strings.
    """
    conn = get_connection()
    cur = conn.execute(
    	"""SELECT player_id 
			FROM players_recorded 
   			WHERE region = ? AND queue = ? AND tier = ? AND division = ? AND 
      		datetime(json_extract(paths_logged_at, '$[' || (json_array_length(paths_logged_at) - 1) || ']')) 
        		> datetime('now', ?)""",
    	(region, queue, tier, division, f'-{days_ago} days')
    )
    players = [row["player_id"] for row in cur.fetchall()]
    conn.close()
    return players