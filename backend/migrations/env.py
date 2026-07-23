"""Alembic env — đọc DATABASE_URL từ app.config (fallback biến môi trường).

Migration ở đây là hand-written (op.create_table), không dùng autogenerate,
nên target_metadata = None. Chạy: `alembic upgrade head` từ thư mục backend/.
"""
from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine

target_metadata = None


def _database_url() -> str:
    # Ưu tiên app.config (đọc .env qua pydantic-settings); fallback env thô
    # để env.py vẫn chạy được khi thiếu pydantic (ví dụ CI tối giản).
    try:
        from app.config import get_settings

        return get_settings().database_url
    except Exception:
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError(
                "Không tìm thấy DATABASE_URL — đặt trong backend/.env hoặc biến môi trường."
            )
        return url


def run_migrations_offline() -> None:
    """--sql mode: phát SQL ra stdout, không cần kết nối DB."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), future=True)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
