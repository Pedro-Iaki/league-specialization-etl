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
