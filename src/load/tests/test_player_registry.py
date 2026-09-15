import load.player_registry as pr


def test_upsert_inserts_new_player_as_fresh(registry_conn):
    pr.upsert_players(["reg-test-p1"], "players", conn=registry_conn)

    row = pr.get_player_state("reg-test-p1", conn=registry_conn)

    assert row is not None
    assert row["last_dataset"] == "players"
    assert row["first_loaded_at"] == row["last_updated_at"]
    assert row["is_fresh"] is True


def test_upsert_updates_last_updated_at_but_keeps_first_loaded_at(registry_conn):
    pr.upsert_players(["reg-test-p2"], "players", conn=registry_conn)
    first_seen = pr.get_player_state("reg-test-p2", conn=registry_conn)

    registry_conn.execute(
        "UPDATE player_state_registry SET last_updated_at = now() - interval '1 hour' WHERE puuid = %s",
        ("reg-test-p2",),
    )
    stale = pr.get_player_state("reg-test-p2", threshold_minutes=15, conn=registry_conn)
    assert stale["is_fresh"] is False

    pr.upsert_players(["reg-test-p2"], "masteries", conn=registry_conn)
    second_seen = pr.get_player_state("reg-test-p2", conn=registry_conn)

    assert second_seen["first_loaded_at"] == first_seen["first_loaded_at"]
    assert second_seen["last_updated_at"] != stale["last_updated_at"]
    assert second_seen["last_dataset"] == "masteries"
    assert second_seen["is_fresh"] is True


def test_stale_player_is_flagged_and_returned(registry_conn):
    pr.upsert_players(["reg-test-p3"], "players", conn=registry_conn)
    registry_conn.execute(
        "UPDATE player_state_registry SET last_updated_at = now() - interval '1 hour' WHERE puuid = %s",
        ("reg-test-p3",),
    )

    row = pr.get_player_state("reg-test-p3", threshold_minutes=15, conn=registry_conn)
    stale_puuids = {r["puuid"] for r in pr.get_stale_players(threshold_minutes=15, conn=registry_conn)}

    assert row["is_fresh"] is False
    assert "reg-test-p3" in stale_puuids


def test_upsert_is_a_no_op_for_empty_list(registry_conn):
    affected = pr.upsert_players([], "players", conn=registry_conn)
    assert affected == 0
