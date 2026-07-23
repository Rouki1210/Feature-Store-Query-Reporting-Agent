"""Kết nối DB qua SQLAlchemy — engine-agnostic (Postgres target, SQLite dev).

Chỉ mở kết nối; việc thực thi truy vấn đi qua tầng guard (app.sql.executor),
KHÔNG gọi thẳng engine từ nơi khác.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.config import get_settings

_engine: Engine | None = None


def get_engine() -> Engine:
    """Trả về engine singleton dựng từ DATABASE_URL."""
    global _engine
    if _engine is None:
        settings = get_settings()
        connect_args = {}
        if settings.database_url.startswith("sqlite"):
            # SQLite: cho phép dùng chung engine giữa các thread của FastAPI.
            connect_args = {"check_same_thread": False}
        _engine = create_engine(
            settings.database_url,
            future=True,
            connect_args=connect_args,
        )
    return _engine


def dialect_name() -> str:
    return get_engine().dialect.name
