import load.player_registry as pr


def test_upsert_inserts_new_player_as_fresh(registry_conn):
    pr.upsert_players(["reg-test-p1"], "players", conn=registry_conn)

    row = pr.get_player_state("reg-test-p1", "players", conn=registry_conn)

    assert row is not None
    assert row["dataset"] == "players"
    assert row["first_loaded_at"] == row["last_updated_at"]
    assert row["is_fresh"] is True


def test_upsert_updates_last_updated_at_but_keeps_first_loaded_at(registry_conn):
    pr.upsert_players(["reg-test-p2"], "players", conn=registry_conn)
    first_seen = pr.get_player_state("reg-test-p2", "players", conn=registry_conn)

    registry_conn.execute(
        "UPDATE player_state_registry SET last_updated_at = now() - interval '1 hour' WHERE puuid = %s AND dataset = %s",
        ("reg-test-p2", "players"),
    )
    stale = pr.get_player_state("reg-test-p2", "players", threshold_minutes=15, conn=registry_conn)
    assert stale is not None
    assert stale["is_fresh"] is False

    pr.upsert_players(["reg-test-p2"], "players", conn=registry_conn)
    second_seen = pr.get_player_state("reg-test-p2", "players", conn=registry_conn)

    assert first_seen is not None
    assert stale is not None
    assert second_seen is not None
    assert second_seen["first_loaded_at"] == first_seen["first_loaded_at"]
    assert second_seen["last_updated_at"] != stale["last_updated_at"]
    assert second_seen["is_fresh"] is True


def test_same_puuid_different_dataset_are_independent_rows(registry_conn):
    pr.upsert_players(["reg-test-p2b"], "players", conn=registry_conn)
    pr.upsert_players(["reg-test-p2b"], "masteries", conn=registry_conn)

    players_row = pr.get_player_state("reg-test-p2b", "players", conn=registry_conn)
    masteries_row = pr.get_player_state("reg-test-p2b", "masteries", conn=registry_conn)

    assert players_row is not None and masteries_row is not None
    assert players_row["dataset"] == "players"
    assert masteries_row["dataset"] == "masteries"


def test_stale_player_is_flagged_and_returned(registry_conn):
    pr.upsert_players(["reg-test-p3"], "players", conn=registry_conn)
    registry_conn.execute(
        "UPDATE player_state_registry SET last_updated_at = now() - interval '1 hour' WHERE puuid = %s AND dataset = %s",
        ("reg-test-p3", "players"),
    )

    row = pr.get_player_state("reg-test-p3", "players", threshold_minutes=15, conn=registry_conn)
    stale_puuids = {
        r["puuid"] for r in pr.get_stale_players(threshold_minutes=15, dataset="players", conn=registry_conn)
    }

    assert row is not None
    assert row["is_fresh"] is False
    assert "reg-test-p3" in stale_puuids


def test_upsert_is_a_no_op_for_empty_list(registry_conn):
    affected = pr.upsert_players([], "players", conn=registry_conn)
    assert affected == 0


def test_claim_stale_players_marks_claimed_and_excludes_from_next_claim(registry_conn):
    pr.upsert_players(["reg-test-p4"], "players", conn=registry_conn)
    registry_conn.execute(
        "UPDATE player_state_registry SET last_updated_at = now() - interval '1 hour' WHERE puuid = %s AND dataset = %s",
        ("reg-test-p4", "players"),
    )

    claimed = pr.claim_stale_players(limit=10, run_id="worker-a", threshold_minutes=15, conn=registry_conn)
    assert "reg-test-p4" in claimed

    again = pr.claim_stale_players(limit=10, run_id="worker-b", threshold_minutes=15, conn=registry_conn)
    assert "reg-test-p4" not in again


def test_release_claims_makes_player_claimable_again(registry_conn):
    pr.upsert_players(["reg-test-p5"], "players", conn=registry_conn)
    registry_conn.execute(
        "UPDATE player_state_registry SET last_updated_at = now() - interval '1 hour' WHERE puuid = %s AND dataset = %s",
        ("reg-test-p5", "players"),
    )

    pr.claim_stale_players(limit=10, run_id="worker-a", threshold_minutes=15, conn=registry_conn)
    pr.release_claims(["reg-test-p5"], conn=registry_conn)

    again = pr.claim_stale_players(limit=10, run_id="worker-b", threshold_minutes=15, conn=registry_conn)
    assert "reg-test-p5" in again


def test_release_expired_claims_reaps_stuck_claims(registry_conn):
    pr.upsert_players(["reg-test-p6"], "players", conn=registry_conn)
    registry_conn.execute(
        "UPDATE player_state_registry SET last_updated_at = now() - interval '1 hour' WHERE puuid = %s AND dataset = %s",
        ("reg-test-p6", "players"),
    )
    pr.claim_stale_players(limit=10, run_id="worker-a", threshold_minutes=15, conn=registry_conn)
    registry_conn.execute(
        "UPDATE player_state_registry SET claimed_at = now() - interval '1 hour' WHERE puuid = %s AND dataset = %s",
        ("reg-test-p6", "players"),
    )

    reaped = pr.release_expired_claims(claim_timeout_minutes=30, conn=registry_conn)
    assert reaped >= 1

    again = pr.claim_stale_players(limit=10, run_id="worker-b", threshold_minutes=15, conn=registry_conn)
    assert "reg-test-p6" in again
