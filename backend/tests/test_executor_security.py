from __future__ import annotations

from unittest.mock import Mock

from app.config import Settings
from app.sql.executor import _prepare_query_connection


def test_postgres_query_sets_reader_role_and_timeout():
    conn = Mock()
    conn.dialect.name = "postgresql"
    _prepare_query_connection(conn, Settings(SQL_TIMEOUT_MS=1234))
    sql = [str(call.args[0]) for call in conn.execute.call_args_list]
    assert "SET LOCAL ROLE feature_agent_reader" in sql[0]
    assert "SET LOCAL statement_timeout = 1234" in sql[1]
