import json
from datetime import datetime, timedelta, timezone

import extract.extraction_db_helper as db
import extract.tests.t_utilities as util

util.set_path_for_extract_modules()


def test_connection_helpers_and_now():
    assert db.is_active()

    conn = db.get_connection()
    foreign_keys_enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert foreign_keys_enabled == 1
    conn.close()

    ts = db.now()
    parsed = datetime.fromisoformat(ts)
    assert parsed.tzinfo is not None


def test_run_lifecycle_operators(mock_conn):
    run_id = db.start_run("unit_test_run", conn=mock_conn)
    assert run_id > 0

    run = mock_conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    assert run["status"] == "running"
    assert run["started_at"] is not None

    db.heartbeat_run(run_id, conn=mock_conn)
    heartbeat = mock_conn.execute(
        "SELECT last_heartbeat FROM runs WHERE run_id = ?", (run_id,)
    ).fetchone()[0]
    assert heartbeat is not None

    db.finish_run(run_id, "failed", "simulated failure", conn=mock_conn)
    finished = mock_conn.execute(
        "SELECT status, finished_at, error_message FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    assert finished["status"] == "failed"
    assert finished["finished_at"] is not None
    assert finished["error_message"] == "simulated failure"


def test_player_task_lifecycle_operators(mock_conn):
    run_id = db.start_run("player_task_lifecycle", conn=mock_conn)
    task_id = db.add_player_task(run_id, conn=mock_conn)
    assert task_id > 0

    task = mock_conn.execute(
        "SELECT status, attempts FROM player_tasks WHERE task_id = ?", (task_id,)
    ).fetchone()
    assert task["status"] == "pending"
    assert task["attempts"] == 0

    db.update_player_task(task_id, "in_progress", conn=mock_conn)
    task = mock_conn.execute(
        "SELECT status, attempts, started_at FROM player_tasks WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    assert task["status"] == "in_progress"
    assert task["attempts"] == 1
    assert task["started_at"] is not None

    db.update_player_task(
        task_id, "success", file_path="/tmp/player_snapshot.json", conn=mock_conn
    )
    task = mock_conn.execute(
        "SELECT status, finished_at, file_path FROM player_tasks WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    assert task["status"] == "success"
    assert task["finished_at"] is not None


def test_player_record_and_mastery_operators(mock_conn):
    run_id = db.start_run("record_mastery_ops", conn=mock_conn)
    player_task_id = db.add_player_task(run_id, conn=mock_conn)
    player_id = "player-record-mastery"

    db.add_player_records(
        player_id,
        "/tmp/p1.json",
        player_task_id,
        "na1",
        "RANKED_SOLO_5x5",
        "GOLD",
        "I",
        "14.1",
        conn=mock_conn,
    )
    db.add_player_records(
        player_id,
        "/tmp/p2.json",
        player_task_id + 1,
        "na1",
        "RANKED_SOLO_5x5",
        "PLATINUM",
        "II",
        "14.2",
        conn=mock_conn,
    )

    record = mock_conn.execute(
        "SELECT * FROM players_recorded WHERE player_id = ?", (player_id,)
    ).fetchone()
    player_task_ids = json.loads(record["player_task_ids"])
    paths = json.loads(record["paths"])
    patches = json.loads(record["patches_logged"])
    assert len(player_task_ids) == 2
    assert player_task_ids[-1] == player_task_id + 1
    assert paths[-1] == "/tmp/p2.json"
    assert patches[-1] == "14.2"
    assert record["tier"] == "PLATINUM"
    assert record["division"] == "II"

    mastery_task_id = db.add_mastery_task(run_id, player_id, conn=mock_conn)
    db.update_mastery_task(
        mastery_task_id,
        "success",
        patch="14.2",
        file_path="/tmp/mastery_player-record-mastery.json",
        conn=mock_conn,
    )

    mastery = mock_conn.execute(
        "SELECT * FROM mastery_tasks WHERE task_id = ?", (mastery_task_id,)
    ).fetchone()
    record = mock_conn.execute(
        "SELECT * FROM players_recorded WHERE player_id = ?", (player_id,)
    ).fetchone()
    assert mastery["status"] == "success"
    assert mastery["file_path"] == "/tmp/mastery_player-record-mastery.json"
    assert record["mastery_status"] == "success"
    assert record["mastery_path"] == "/tmp/mastery_player-record-mastery.json"
    assert record["mastery_task_id"] == mastery_task_id
    assert record["mastery_patch"] == "14.2"


def test_update_player_records_direct_operator(db_factory, mock_conn):
    factory = db_factory(mock_conn)
    run_id = factory.create_individual_run()
    player_id = factory.get_uuid()
    mastery_file_path = f"/tmp/mastery_{player_id}.json"
    mastery_task_id = factory.create_individual_mastery_task(
        {
            "run_id": run_id,
            "player_id": player_id,
            "status": "pending",
            "file_path": mastery_file_path,
        }
    )
    factory.create_individual_players_recorded(
        {"player_id": player_id, "mastery_status": "pending"}
    )

    db.update_player_records(
        "failed",
        mastery_file_path,
        player_id,
        "15.3",
        mock_conn,
        mastery_task_id=mastery_task_id,
    )

    record = mock_conn.execute(
        "SELECT * FROM players_recorded WHERE player_id = ?", (player_id,)
    ).fetchone()
    assert record["mastery_status"] == "failed"
    assert record["mastery_path"] == mastery_file_path
    assert record["mastery_task_id"] == mastery_task_id
    assert record["mastery_patch"] == "15.3"
    assert record["mastery_logged_at"] is not None


def test_get_mastery_id_from_list_operator(mock_conn, db_factory):
    factory = db_factory(mock_conn)
    run_id = factory.create_individual_run()
    p1 = factory.get_uuid()
    p2 = factory.get_uuid()
    id1 = factory.create_individual_mastery_task({"run_id": run_id, "player_id": p1})
    id2 = factory.create_individual_mastery_task({"run_id": run_id, "player_id": p2})

    found = db.get_mastery_id_from_list([id1, id2], p1, conn=mock_conn)
    missing = db.get_mastery_id_from_list([id1, id2], "unknown-player", conn=mock_conn)

    assert found == id1
    assert missing == -1


def test_player_query_operators(mock_conn, db_factory):
    factory = db_factory(mock_conn)
    now_iso = datetime.now(timezone.utc).isoformat()
    recent = datetime.now(timezone.utc) - timedelta(hours=2)
    old = datetime.now(timezone.utc) - timedelta(days=10)

    pending_id = factory.create_individual_players_recorded(
        {
            "mastery_status": "pending",
            "paths_logged_at": json.dumps([recent.isoformat()]),
            "mastery_logged_at": None,
            "mastery_patch": "15.1",
        }
    )
    failed_id = factory.create_individual_players_recorded(
        {
            "mastery_status": "failed",
            "paths_logged_at": json.dumps([recent.isoformat()]),
            "mastery_logged_at": old.isoformat(),
            "mastery_patch": "15.1",
        }
    )
    stale_success_id = factory.create_individual_players_recorded(
        {
            "mastery_status": "success",
            "paths_logged_at": json.dumps([recent.isoformat()]),
            "mastery_logged_at": old.isoformat(),
            "mastery_patch": "15.1",
        }
    )
    in_progress_id = factory.create_individual_players_recorded(
        {
            "mastery_status": "in_progress",
            "paths_logged_at": json.dumps([recent.isoformat()]),
            "mastery_logged_at": old.isoformat(),
            "mastery_patch": "15.1",
        }
    )

    missing_default = db.claim_players_missing_masteries(conn=mock_conn, claim=False)
    assert pending_id in missing_default
    assert failed_id in missing_default
    assert stale_success_id not in missing_default

    stale_candidates = db.claim_players_missing_masteries(
        include_stale_success=True, conn=mock_conn, claim=False
    )
    assert stale_success_id in stale_candidates
    assert in_progress_id not in stale_candidates

    limited = db.claim_players_missing_masteries(limit=1, conn=mock_conn, claim=False)
    assert len(limited) == 1

    assert db.get_mastery_status_for_player(pending_id, conn=mock_conn) == "pending"
    assert db.get_mastery_status_for_player("missing-player", conn=mock_conn) == "None"

    info = db.get_player_info(pending_id, conn=mock_conn)
    assert info is not None
    assert info["puuid"] == pending_id
    assert isinstance(info["latest_logged_at"], datetime)

    players_recent = db.get_players_in_timespan(7, conn=mock_conn)
    assert pending_id in players_recent

    players_recent_filtered = db.get_players_in_timespan(
        7,
        region="na1",
        queue="RANKED_SOLO_5x5",
        tier="GOLD",
        division="I",
        conn=mock_conn,
    )
    assert pending_id in players_recent_filtered

    players_patch = db.get_players_in_patch("15.1", conn=mock_conn)
    assert stale_success_id in players_patch

    players_patch_filtered = db.get_players_in_patch(
        "15.1",
        region="na1",
        queue="RANKED_SOLO_5x5",
        tier="GOLD",
        division="I",
        conn=mock_conn,
    )
    assert failed_id in players_patch_filtered
    assert now_iso is not None


def test_page_tracking_operators(mock_conn, db_factory):
    factory = db_factory(mock_conn)
    region = "na1"
    queue = "RANKED_SOLO_5x5"
    patch = "16.2"
    tiers = ["GOLD", "SILVER"]
    divisions = ["I", "II"]

    stats = db.get_page_info(region, queue, patch, tiers, divisions, conn=mock_conn)
    assert set(stats.keys()) == {
        ("GOLD", "I"),
        ("GOLD", "II"),
        ("SILVER", "I"),
        ("SILVER", "II"),
    }
    assert all(value == (0, 0) for value in stats.values())

    factory.create_individual_tier_division_page(
        {
            "region": region,
            "queue": queue,
            "tier": "GOLD",
            "division": "I",
            "patch": patch,
            "current_page": 3,
            "last_player_count": 10,
            "loop_count": 2,
        }
    )
    for _ in range(3):
        factory.create_individual_players_recorded(
            {
                "region": region,
                "queue": queue,
                "tier": "GOLD",
                "division": "I",
                "mastery_patch": patch,
                "mastery_status": "success",
            }
        )

    stats = db.get_page_info(region, queue, patch, tiers, divisions, conn=mock_conn)
    assert stats[("GOLD", "I")][0] == 2
    assert stats[("GOLD", "I")][1] == 3

    page_missing = db.get_page_and_loop(
        region, queue, "EMERALD", "III", patch, conn=mock_conn
    )
    assert page_missing == (1, 0)

    missing_update = db.update_page_info(
        "xx", "yy", "zz", "ww", "pp", 12, conn=mock_conn
    )
    assert missing_update == 0

    db.update_page_info(
        region, queue, "GOLD", "I", patch, player_count=12, conn=mock_conn
    )
    row = mock_conn.execute(
        "SELECT current_page, last_player_count, loop_count FROM tier_division_pages WHERE region=? AND queue=? AND tier=? AND division=? AND patch=?",
        (region, queue, "GOLD", "I", patch),
    ).fetchone()
    assert row["current_page"] == 4
    assert row["last_player_count"] == 12
    assert row["loop_count"] == 2

    db.update_page_info(
        region, queue, "GOLD", "I", patch, player_count=5, conn=mock_conn
    )
    row = mock_conn.execute(
        "SELECT current_page, last_player_count, loop_count FROM tier_division_pages WHERE region=? AND queue=? AND tier=? AND division=? AND patch=?",
        (region, queue, "GOLD", "I", patch),
    ).fetchone()
    assert row["current_page"] == 1
    assert row["last_player_count"] == 5
    assert row["loop_count"] == 3
