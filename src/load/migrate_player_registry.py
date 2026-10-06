"""Apply the idempotent player registry schema through a direct connection."""

from load.player_registry import ensure_schema, get_connection


def main() -> None:
    with get_connection(direct=True) as conn:
        ensure_schema(conn)
        columns = conn.execute(
            """
            SELECT count(*) FROM information_schema.columns
            WHERE table_name = 'player_state_registry'
              AND column_name IN ('queue_games_total', 'inactive_streak')
            """
        ).fetchone()
        rank_pages = conn.execute("SELECT to_regclass('public.rank_page_progress') IS NOT NULL").fetchone()
        if columns is None or columns[0] != 2 or rank_pages is None or not rank_pages[0]:
            raise RuntimeError("Player registry migration verification failed")
    print("Player registry schema is ready")


if __name__ == "__main__":
    main()
