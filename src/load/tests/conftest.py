import pytest

import load.player_registry as pr


@pytest.fixture
def registry_conn():
    """Neon connection"""
    conn = pr.get_connection()
    pr.ensure_schema(conn)
    yield conn
    conn.rollback()
    conn.close()
