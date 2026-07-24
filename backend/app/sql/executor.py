"""Thực thi truy vấn có bảo vệ (read-only).

Mọi SQL đi qua đây PHẢI qua guards trước. Không có đường tắt tới engine.
"""
from __future__ import annotations

import datetime
import decimal
import json
import time
from typing import Any

from sqlalchemy import text

from app.config import Settings, get_settings
from app.db import get_engine
from app.models.schemas import QueryResult
from app.sql.guards import GuardError, has_select_star, referenced_tables, validate_sql


def _jsonable(v: Any) -> Any:
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    return v


def run_query(
    sql: str,
    settings: Settings | None = None,
    *,
    query_text: str | None = None,
    session_id: str | None = None,
) -> tuple[str, QueryResult]:
    """Validate → thực thi → trả (safe_sql, QueryResult).

    Raise GuardError nếu SQL không an toàn; raise DBAPIError nếu SQL lỗi cú pháp
    (pipeline sẽ bắt để chạy vòng tự sửa).
    """
    settings = settings or get_settings()
    engine = get_engine()
    started = time.perf_counter()
    try:
        safe_sql = validate_sql(sql, settings)
    except GuardError as exc:
        with engine.begin() as conn:
            query_id = conn.execute(text("""
                INSERT INTO agent.query_log
                  (session_id, query_text, generated_sql, execution_status, error_message)
                VALUES (:session, :question, :sql, 'rejected', :error)
                RETURNING query_id
            """), {"session": session_id, "question": query_text or sql, "sql": sql, "error": str(exc)}).scalar_one()
            conn.execute(text("""
                INSERT INTO agent.sql_validation_log
                  (query_id, validator_version, sql_text, is_select_only, has_select_star,
                   accesses_raw_schema, has_disallowed_statement, referenced_tables,
                   validation_errors, is_valid)
                VALUES (:id, 'sprint1-v1', :sql, FALSE, :star, :raw, TRUE,
                        CAST(:tables AS jsonb), CAST(:errors AS jsonb), FALSE)
            """), {
                "id": query_id, "sql": sql, "star": has_select_star(sql), "raw": "raw." in sql.lower(),
                "tables": json.dumps(referenced_tables(sql)), "errors": json.dumps([str(exc)]),
            })
        raise

    try:
        with engine.connect() as conn:
            result = conn.execute(text(safe_sql))
            columns = list(result.keys())
            raw_rows = result.fetchall()
    except Exception as exc:
        with engine.begin() as conn:
            query_id = conn.execute(text("""
                INSERT INTO agent.query_log
                  (session_id, query_text, generated_sql, validated_sql, execution_status,
                   execution_time_ms, error_message)
                VALUES (:session, :question, :sql, :safe, 'failed', :ms, :error)
                RETURNING query_id
            """), {
                "session": session_id, "question": query_text or sql, "sql": sql, "safe": safe_sql,
                "ms": int((time.perf_counter() - started) * 1000), "error": str(exc),
            }).scalar_one()
            conn.execute(text("""
                INSERT INTO agent.sql_validation_log
                  (query_id, validator_version, sql_text, is_select_only,
                   has_select_star, accesses_raw_schema, has_disallowed_statement,
                   has_row_limit, referenced_tables, validation_errors, is_valid)
                VALUES (:id, 'sprint1-v1', :sql, TRUE, FALSE, FALSE, FALSE, TRUE,
                        CAST(:tables AS jsonb), '[]'::jsonb, TRUE)
            """), {
                "id": query_id, "sql": safe_sql,
                "tables": json.dumps(referenced_tables(safe_sql)),
            })
        raise

    rows = [[_jsonable(v) for v in row] for row in raw_rows]
    truncated = len(rows) >= settings.sql_max_rows
    query_result = QueryResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
    )
    with engine.begin() as conn:
        query_id = conn.execute(text("""
            INSERT INTO agent.query_log
              (session_id, query_text, selected_tables, generated_sql, validated_sql,
               execution_status, row_count, execution_time_ms, result_preview)
            VALUES (:session, :question, CAST(:tables AS jsonb), :sql, :safe, 'executed',
                    :count, :ms, CAST(:preview AS jsonb))
            RETURNING query_id
        """), {
            "session": session_id, "question": query_text or sql,
            "tables": json.dumps(referenced_tables(safe_sql)), "sql": sql, "safe": safe_sql,
            "count": len(rows), "ms": int((time.perf_counter() - started) * 1000),
            "preview": json.dumps({"columns": columns, "rows": rows[:5]}, ensure_ascii=False),
        }).scalar_one()
        conn.execute(text("""
            INSERT INTO agent.sql_validation_log
              (query_id, validator_version, sql_text, is_select_only, has_select_star,
               accesses_raw_schema, has_disallowed_statement, has_row_limit,
               referenced_tables, validation_errors, is_valid)
            VALUES (:id, 'sprint1-v1', :sql, TRUE, FALSE, FALSE, FALSE, TRUE,
                    CAST(:tables AS jsonb), '[]'::jsonb, TRUE)
        """), {"id": query_id, "sql": safe_sql, "tables": json.dumps(referenced_tables(safe_sql))})
    return safe_sql, query_result
