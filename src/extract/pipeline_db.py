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


def finish_run(run_id: int, status: str, error_message: str=None):
    conn = get_connection()
    conn.execute(
        "UPDATE runs SET finished_at=?, status=?, error_message=? WHERE run_id=?",
        (now(), status, error_message, run_id)
    )
    conn.commit()
    conn.close()


def add_player_task(run_id: int, region: str, queue: str, tier: str, division: str) -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO player_tasks (run_id, region, queue, tier, division, status) VALUES (?, ?, ?, ?, ?, 'pending')",
        (run_id, region, queue, tier, division)
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

    
def add_player_records(player_id: str, file_path: str):
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO players_recorded (player_id, paths, mastery_status, logged_at)
        VALUES (?, json_array(?), 'waiting', json_array(?))
        ON CONFLICT(player_id) DO UPDATE SET
            paths = json_insert(paths, '$[#]', ?),
            mastery_status = 'waiting',
            logged_at = json_insert(logged_at, '$[#]', ?)
        """,
        (player_id, file_path, now(), file_path, now())
    )
    conn.commit()
    conn.close()

    
def add_mastery_task(run_id: int, region: str, queue: str, tier: str, division: str, player_id: str) -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO mastery_tasks (run_id, region, queue, tier, division, player_id, status) VALUES (?, ?, ?, ?, ?, ?, 'pending')",
        (run_id, region, queue, tier, division, player_id)
    )
    conn.commit()
    task_id = cur.lastrowid
    conn.close()
    return task_id


def update_mastery_task(task_id: int, status: str, file_path: str=None, error_message: str=None):
    conn = get_connection()
    if status == "in_progress":
        conn.execute(
            "UPDATE mastery_tasks SET status=?, started_at=?, attempts=attempts+1 WHERE task_id=?",
            (status, now(), task_id)
        )
    else:  # success or failed
        player_id = conn.execute("SELECT player_id FROM mastery_tasks WHERE task_id=?", (task_id,)).fetchone()["player_id"]
        conn.execute(
            """
            UPDATE mastery_tasks 
            SET status=?, 
				finished_at=?, 
				file_path=?, 
				error_message=?,
				duplicated = (SELECT COUNT(*) FROM mastery_tasks WHERE player_id=? AND status='success') > 1
            WHERE task_id=?
            """,
            (status, now(), file_path, error_message, player_id, task_id)
        )
        conn.execute(
            """
            UPDATE players_recorded
            SET mastery_status = ?,
                mastery_path = ?
            WHERE player_id = ?
            """,
            (status, file_path, player_id)
        )
    conn.commit()
    conn.close()

    
def get_task_from_list_with_puuid(task_ids: list[int], puuid: str) -> int:
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
    Clean up leftover data from interrupted pipeline runs.
    Updates any incomplete tasks and runs marked as 'running' to 'failed'.
    """
    conn = get_connection()
    
    # Mark incomplete player_tasks as failed
    conn.execute(
        "UPDATE player_tasks SET status='failed', finished_at=?, error_message=? WHERE status != 'success'",
        (now(), 'Pipeline interrupted - cleanup on restart')
    )
    
    # Mark incomplete mastery_tasks as failed
    conn.execute(
        "UPDATE mastery_tasks SET status='failed', finished_at=?, error_message=? WHERE status != 'success'",
        (now(), 'Pipeline interrupted - cleanup on restart')
    )
    
    # Mark runs still in 'running' status as failed
    conn.execute(
        "UPDATE runs SET status='failed', finished_at=?, error_message=? WHERE status != 'success'",
        (now(), 'Pipeline interrupted - cleanup on restart')
    )
    
    # Mark player and mastery tasks with the run_id of a failed run as failed
    conn.execute(
		"""
		UPDATE player_tasks
		SET status='failed', finished_at=?, error_message='Run Failed - Cancelled due to failed run'
		WHERE run_id IN (SELECT run_id FROM runs WHERE status='failed')
		""",
		(now(),)
	)
    conn.execute(
		"""
		UPDATE mastery_tasks
		SET status='failed', finished_at=?, error_message='Run Failed - Cancelled due to failed run'
		WHERE run_id IN (SELECT run_id FROM runs WHERE status='failed')
		""",
		(now(),)
	)
    
    # Mark players_recorded entries with 'pending' mastery_status as 'failed'
    conn.execute(
        "UPDATE players_recorded SET mastery_status='failed', logged_at=? WHERE mastery_status != 'success' OR mastery_path IS NULL",
        (now(),)
    )
    # Go through all paths in players_recorded and check if all correspond to a failed player_task, if so, mark the player as failed
    conn.execute(
        """
        UPDATE players_recorded
        SET mastery_status='failed'
        WHERE player_id IN (
            SELECT DISTINCT pr.player_id
            FROM players_recorded pr
            WHERE NOT EXISTS (
                SELECT 1 FROM player_tasks pt
                WHERE pt.file_path IN (SELECT json_extract(pr.paths, '$[' || (json_array_length(pr.paths) - 1) || ']'))
                AND pt.status = 'success'
            )
            AND json_array_length(pr.paths) > 0
        )
        """
    )
    
    conn.commit()
    conn.close()

