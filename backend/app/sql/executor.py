"""Thực thi truy vấn có bảo vệ (read-only).

Mọi SQL đi qua đây PHẢI qua guards trước. Không có đường tắt tới engine.
"""
from __future__ import annotations

import datetime
import decimal
from typing import Any

from sqlalchemy import text

from app.config import Settings, get_settings
from app.db import get_engine
from app.models.schemas import QueryResult
from app.sql.guards import validate_sql


def _jsonable(v: Any) -> Any:
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    return v


def run_query(sql: str, settings: Settings | None = None) -> tuple[str, QueryResult]:
    """Validate → thực thi → trả (safe_sql, QueryResult).

    Raise GuardError nếu SQL không an toàn; raise DBAPIError nếu SQL lỗi cú pháp
    (pipeline sẽ bắt để chạy vòng tự sửa).
    """
    settings = settings or get_settings()
    safe_sql = validate_sql(sql, settings)

    engine = get_engine()
    with engine.connect() as conn:
        # Read-only ở tầng transaction; guard đã bảo đảm chỉ SELECT/WITH.
        result = conn.execute(text(safe_sql))
        columns = list(result.keys())
        raw_rows = result.fetchall()

    rows = [[_jsonable(v) for v in row] for row in raw_rows]
    truncated = len(rows) >= settings.sql_max_rows
    return safe_sql, QueryResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
    )
