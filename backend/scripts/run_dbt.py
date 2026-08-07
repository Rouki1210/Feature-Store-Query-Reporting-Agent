"""Chạy dbt với thông tin kết nối lấy từ app.config (tức backend/.env).

Vì sao cần wrapper thay vì gọi `dbt` trực tiếp: dbt KHÔNG đọc backend/.env. Nếu để
profiles.yml dùng env_var() rồi export tay thì trên Windows vừa phiền vừa dễ quên —
quên một biến là dbt lặng lẽ chạy vào database khác, đúng cái bẫy đã gặp một lần với
DATABASE_URL trỏ nhầm cổng 5432. Wrapper nạp settings vào os.environ rồi mới gọi dbt,
nên dbt và app luôn trỏ CÙNG một database.

dbt chạy bằng role `dbt_transformer` (migration 0015), KHÔNG phải superuser của app:
DML trên feature.*, toàn quyền trên silver/dbt_work, không có DDL trên feature.*.

Cách chạy (từ thư mục backend/):
    python -m scripts.run_dbt debug
    python -m scripts.run_dbt build --select silver
    python -m scripts.run_dbt run --select int_gsm_feature_candidate
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

def _reopen_utf8() -> None:
    """Chạy lại chính mình với -X utf8 nếu chưa ở chế độ đó.

    Gọi từ khối `__main__`, KHÔNG gọi lúc import: scripts/publish_gold.py dùng lại
    build_env() của module này, mà một import gây re-exec là tác dụng phụ không ai ngờ.
    """
    if sys.flags.utf8_mode:
        return
    # dbt đọc file project bằng encoding mặc định của LOCALE (cp1258 trên máy này),
    # không phải UTF-8 — nên một dấu tiếng Việt trong dbt_project.yml hay trong comment
    # của model là đủ để nó chết UnicodeDecodeError. PYTHONIOENCODING không cứu được:
    # nó chỉ đổi stdout, không đổi open(). Biến PYTHONUTF8 phải có TRƯỚC khi interpreter
    # khởi động, nên cách duy nhất là chạy lại chính mình với -X utf8.
    # sys.orig_argv giữ nguyên dạng gọi ban đầu (-m scripts.run_dbt ... hoặc đường dẫn file).
    #
    # subprocess chứ KHÔNG os.execv: trên Windows execv nối tham số lại theo quy tắc
    # quoting của CRT và nuốt mất dấu ngoặc kép, nên `--vars '{"k": "v"}'` tới dbt thành
    # `{k: v}` và dbt báo "YAML không hợp lệ". subprocess dùng list2cmdline nên escape đúng.
    import subprocess

    sys.exit(subprocess.run([sys.executable, "-X", "utf8", *sys.orig_argv[1:]]).returncode)


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.engine import make_url

from app.config import get_settings

# backend/scripts/run_dbt.py -> parents[2] = gốc repo
DBT_DIR = Path(__file__).resolve().parents[2] / "dbt"


def build_env() -> dict[str, str]:
    """Suy ra biến DBT_* từ DATABASE_URL — một nguồn sự thật cho 'database nào'."""
    settings = get_settings()
    if not settings.dbt_transformer_password:
        raise SystemExit(
            "Thiếu DBT_TRANSFORMER_PASSWORD trong backend/.env. Role dbt_transformer do "
            "migration 0015 tạo — xem docs/dbt_migration_runbook.md."
        )
    url = make_url(settings.database_url)
    return {
        "DBT_HOST": url.host or "localhost",
        "DBT_PORT": str(url.port or 5432),
        "DBT_DBNAME": url.database or "feature_store",
        # Cố tình KHÔNG lấy url.username: app kết nối bằng superuser, dbt thì không
        # được phép. Đây là chỗ least-privilege của migration 0015 thực sự có hiệu lực.
        "DBT_USER": "dbt_transformer",
        "DBT_PASSWORD": settings.dbt_transformer_password,
    }


def main(argv: list[str]) -> int:
    if not argv:
        raise SystemExit("Dùng: python -m scripts.run_dbt <lệnh dbt> [tuỳ chọn]")

    env = build_env()
    os.environ.update(env)
    # Pipeline dữ liệu nội bộ không gửi telemetry ra ngoài.
    os.environ.setdefault("DO_NOT_TRACK", "1")

    # Import trễ: chỉ tầng pipeline mới cần dbt, image agent không cài nó.
    from dbt.cli.main import dbtRunner

    args = list(argv)
    for flag, value in (("--project-dir", DBT_DIR), ("--profiles-dir", DBT_DIR)):
        if flag not in args:
            args += [flag, str(value)]

    print(
        f"dbt {' '.join(argv)}  ->  "
        f"{env['DBT_USER']}@{env['DBT_HOST']}:{env['DBT_PORT']}/{env['DBT_DBNAME']}"
    )
    result = dbtRunner().invoke(args)
    return 0 if result.success else 1


if __name__ == "__main__":
    _reopen_utf8()
    raise SystemExit(main(sys.argv[1:]))
