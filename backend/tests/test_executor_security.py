from __future__ import annotations

from unittest.mock import Mock

import pytest
from sqlalchemy import text

from app.config import Settings
from app.db import get_engine
from app.sql.executor import _prepare_query_connection, run_query
from app.sql.guards import GuardError


def test_postgres_query_sets_reader_role_and_timeout():
    conn = Mock()
    conn.dialect.name = "postgresql"
    _prepare_query_connection(conn, Settings(SQL_TIMEOUT_MS=1234))
    sql = [str(call.args[0]) for call in conn.execute.call_args_list]
    assert "SET LOCAL ROLE feature_agent_reader" in sql[0]
    assert "SET LOCAL statement_timeout = 1234" in sql[1]


def test_postgres_statement_timeout_cuts_slow_query():
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        pytest.skip("statement_timeout is PostgreSQL-specific")
    with engine.connect() as conn:
        with pytest.raises(Exception, match="timeout|statement"):
            _prepare_query_connection(conn, Settings(SQL_TIMEOUT_MS=1))
            conn.execute(text("SELECT pg_sleep(0.05)"))


def test_guard_rejection_is_audited_with_join_plan():
    session_id = "pytest-sprint2-guard-rejection"
    plan = {"tables": ["feature.gsm_transaction", "feature.vinfast_transaction"]}
    with pytest.raises(GuardError):
        run_query("SELECT customer_id FROM raw.customers", session_id=session_id, join_plan=plan)
    with get_engine().connect() as conn:
        row = conn.execute(text("""
            SELECT q.execution_status, q.join_plan, v.is_valid, v.validation_errors
            FROM agent.query_log q
            JOIN agent.sql_validation_log v ON v.query_id = q.query_id
            WHERE q.session_id = :session
            ORDER BY q.query_id DESC LIMIT 1
        """), {"session": session_id}).mappings().one()
    assert row["execution_status"] == "rejected"
    assert row["join_plan"] == plan
    assert row["is_valid"] is False
    assert row["validation_errors"]
