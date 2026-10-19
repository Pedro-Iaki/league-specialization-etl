import sqlite3

import pytest

from extract import extraction_db_helper as db
from extract import get_masteries


def seed_mastery_candidates(conn):
    for player_id, status in (("pending", "pending"), ("stale-1", "success"), ("stale-2", "success")):
        conn.execute(
            """INSERT INTO players_recorded
               (player_id, player_task_ids, paths_logged_at, mastery_status, mastery_logged_at)
               VALUES (?, '[]', json_array(datetime('now')), ?, datetime('now', '-10 days'))""",
            (player_id, status),
        )
    conn.commit()


@pytest.mark.parametrize("limit,expected_count", [(1, 1), (2, 2), (3, 3), (None, 3)])
@pytest.mark.parametrize("claim", [False, True])
def test_pending_and_stale_masteries_share_one_limit(mock_conn, limit, expected_count, claim):
    seed_mastery_candidates(mock_conn)

    players = db.claim_players_missing_masteries(
        include_stale_success=True, limit=limit, claim=claim, conn=mock_conn
    )

    assert len(players) == expected_count
    assert "pending" in players
    claimed = {
        row["player_id"]
        for row in mock_conn.execute("SELECT player_id FROM players_recorded WHERE mastery_status = 'in_progress'")
    }
    assert claimed == (set(players) if claim else set())
    remaining = db.claim_players_missing_masteries(include_stale_success=True, claim=False, conn=mock_conn)
    assert len(remaining) == (3 - expected_count if claim else 3)


def test_patch_lookup_failure_leaves_mastery_candidates_claimable(mock_db):
    conn = mock_db.get_connection()
    try:
        seed_mastery_candidates(conn)
    finally:
        conn.close()

    class Client:
        def get_patch(self):
            raise RuntimeError("patch lookup failed")

    with pytest.raises(RuntimeError, match="patch lookup failed"):
        get_masteries.run(1, Client(), limit=1)

    conn = mock_db.get_connection()
    try:
        assert len(db.claim_players_missing_masteries(include_stale_success=True, claim=False, conn=conn)) == 3
        assert conn.execute("SELECT COUNT(*) FROM mastery_tasks").fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.parametrize("limit,expected_count", [(1, 1), (2, 2), (3, 3), (None, 3)])
def test_atomic_claim_links_pending_tasks_within_the_shared_limit(mock_db, limit, expected_count):
    conn = mock_db.get_connection()
    seed_mastery_candidates(conn)
    conn.close()
    run_id = db.start_run("atomic mastery claims")

    tasks = db.claim_mastery_tasks(run_id, include_stale_success=True, limit=limit)

    assert len(tasks) == expected_count
    assert "pending" in tasks
    conn = mock_db.get_connection()
    try:
        for player_id, task_id in tasks.items():
            record = conn.execute("SELECT * FROM players_recorded WHERE player_id = ?", (player_id,)).fetchone()
            task = conn.execute("SELECT * FROM mastery_tasks WHERE task_id = ?", (task_id,)).fetchone()
            assert record["mastery_status"] == "in_progress"
            assert record["mastery_task_id"] == task_id
            assert task["player_id"] == player_id
            assert task["run_id"] == run_id
            assert task["status"] == "pending"
            assert task["attempts"] == 0
        assert conn.execute("SELECT COUNT(*) FROM mastery_tasks").fetchone()[0] == expected_count
    finally:
        conn.close()


def test_atomic_claim_rolls_back_the_entire_batch_if_linking_fails(mock_db):
    run_id = db.start_run("failed atomic claim")
    conn = mock_db.get_connection()
    try:
        seed_mastery_candidates(conn)
        conn.execute(
            """CREATE TRIGGER fail_second_link BEFORE UPDATE OF mastery_task_id ON players_recorded
               WHEN NEW.mastery_task_id IS NOT NULL AND (SELECT COUNT(*) FROM mastery_tasks) = 2
               BEGIN SELECT RAISE(ABORT, 'injected link failure'); END"""
        )
        conn.commit()
        before = [tuple(row) for row in conn.execute("SELECT * FROM players_recorded ORDER BY player_id")]
    finally:
        conn.close()

    with pytest.raises(sqlite3.IntegrityError, match="injected link failure"):
        db.claim_mastery_tasks(run_id, include_stale_success=True)

    conn = mock_db.get_connection()
    try:
        assert [tuple(row) for row in conn.execute("SELECT * FROM players_recorded ORDER BY player_id")] == before
        assert conn.execute("SELECT COUNT(*) FROM mastery_tasks").fetchone()[0] == 0
    finally:
        conn.close()


def test_atomic_claim_leaves_transaction_ownership_with_the_caller(mock_conn):
    seed_mastery_candidates(mock_conn)
    run_id = db.start_run("caller transaction", conn=mock_conn)

    assert len(db.claim_mastery_tasks(run_id, include_stale_success=True, conn=mock_conn)) == 3
    assert mock_conn.in_transaction
    mock_conn.rollback()

    assert mock_conn.execute("SELECT COUNT(*) FROM mastery_tasks").fetchone()[0] == 0
    assert mock_conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    assert mock_conn.execute("SELECT mastery_status FROM players_recorded WHERE player_id = 'pending'").fetchone()[0] == "pending"


def test_interrupted_batch_can_retry_even_tasks_whose_requests_never_started(mock_db):
    conn = mock_db.get_connection()
    seed_mastery_candidates(conn)
    conn.close()
    run_id = db.start_run("interrupted batch")

    class Client:
        def get_patch(self):
            return "16.20"

        def get(self, url):
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        get_masteries.run(run_id, Client(), limit=3)
    db.finish_run(run_id, "failed")
    db.cleanup_failed_run(run_id)

    conn = mock_db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM mastery_tasks WHERE attempts = 0").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM mastery_tasks WHERE status = 'failed'").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM players_recorded WHERE mastery_status = 'failed'").fetchone()[0] == 3
    finally:
        conn.close()
    retry_run = db.start_run("retry interrupted batch")
    assert set(db.claim_mastery_tasks(retry_run)) == {"pending", "stale-1", "stale-2"}
