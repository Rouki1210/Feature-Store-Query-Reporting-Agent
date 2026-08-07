r"""Dagster — hai nút bấm chạy pipeline theo đúng thứ tự.

Dagster KHÔNG thay thế gì cả. `run_dbt.py` và `publish_gold.py` giữ nguyên; ở đây chỉ
gọi lại chúng. Tắt Dagster đi thì ba lệnh dưới vẫn chạy tay được y hệt:

    python -m scripts.generate_mock_data
    python -m scripts.run_dbt build
    python -m scripts.publish_gold

Hai job vì có hai tình huống khác nhau:

    dev_seed_job    raw_events -> dbt_models -> gold_tables     bấm tay
    nightly_job                   dbt_models -> gold_tables     sẽ hẹn giờ

`raw_events` XOÁ SẠCH raw.* và feature.* rồi sinh lại, nên nó KHÔNG BAO GIỜ được nằm
trong job có lịch. Khi cắm dữ liệu thật, nửa trái (`raw_events`) bị thay bằng nguồn
ingest thật, còn `nightly_job` dùng lại nguyên vẹn — đó là toàn bộ lý do tách đôi.

Bản tối giản, CỐ Ý chưa có (xem docs/dbt_migration_runbook.md bước 8):
  * lịch chạy — snapshot_date đang ghim cứng nên chạy đêm ra kết quả y hệt;
  * asset check "raw đã tươi chưa" — phải biết dữ liệu về bằng đường nào mới viết đúng;
  * retry / khoá đồng thời.

Cách chạy (từ thư mục backend/ — .env đọc theo thư mục hiện hành):

    $env:DAGSTER_HOME = "$PWD\.dagster"      # không đặt thì mất lịch sử chạy
    ./.venv/Scripts/dagster.exe dev -m orchestration.definitions
"""
# KHÔNG dùng `from __future__ import annotations` ở file này: nó biến annotation thành
# chuỗi, và Dagster kiểm kiểu tham số `context` lúc định nghĩa asset nên sẽ không nhận ra
# AssetExecutionContext.
import subprocess
import sys
from pathlib import Path

from dagster import (
    AssetExecutionContext,
    AssetSelection,
    Definitions,
    asset,
    define_asset_job,
)

BACKEND = Path(__file__).resolve().parents[1]


def _chay_script(context: AssetExecutionContext, *argv: str) -> None:
    """Gọi một script của backend trong tiến trình con, chế độ UTF-8, cwd = backend/.

    Cả ba asset đều đi qua đây — không asset nào import code của backend rồi gọi hàm.
    Bốn lý do, xếp theo mức độ đã cắn thật:

    1. Tiến trình con của Dagster KHÔNG import được `scripts.*`, kể cả khi đã chèn
       backend/ vào sys.path ở đầu file này. Gọi thẳng hàm asset trong tiến trình cha
       thì chạy tốt, qua executor thì `ModuleNotFoundError`. Đi bằng tiến trình riêng
       là hết hẳn lớp lỗi này thay vì gọt sys.path cho vừa.
    2. cwd. `app/config.py` đọc `.env` theo THƯ MỤC HIỆN HÀNH. Ép `cwd=BACKEND` ở đây
       nghĩa là dù chạy Dagster từ đâu, pipeline vẫn trỏ đúng database — đúng cái bẫy
       đã dính một lần với DATABASE_URL nhầm cổng 5432.
    3. UTF-8. `run_dbt.py` phải chạy với `-X utf8`, nếu không dbt đọc file project bằng
       encoding của LOCALE (cp1258 trên máy này) và chết ngay ở comment tiếng Việt đầu
       tiên. Nó tự re-exec được, nhưng CHỈ khi chạy như `__main__`.
    4. `publish_gold` dùng SystemExit làm chốt chặn ("DỪNG: nguồn rỗng..."). Ở tiến
       trình con nó thành exit code khác 0, tức một lần chạy đỏ gọn gàng.

    Đánh đổi: mất số dòng dưới dạng metadata có cấu trúc trên UI. Chấp nhận được —
    cả ba script đều tự in số dòng ra stdout và Dagster giữ lại trong compute log.
    """
    lenh = [sys.executable, "-X", "utf8", *argv]
    context.log.info("chạy: %s (cwd=%s)", " ".join(argv), BACKEND)
    ket_qua = subprocess.run(lenh, cwd=BACKEND)
    if ket_qua.returncode != 0:
        raise RuntimeError(f"{' '.join(argv)} thất bại (exit={ket_qua.returncode})")


@asset(
    group_name="chi_danh_cho_dev",
    description="Event thô trong raw.* — CHỈ dữ liệu mock. Xoá sạch rồi sinh lại, "
                "kể cả feature.*. Khi có dữ liệu thật, asset này bị thay bằng nguồn ingest.",
)
def raw_events(context: AssetExecutionContext) -> None:
    _chay_script(context, "-m", "scripts.generate_mock_data")
    context.log.info("feature.* đang RỖNG — gold_tables sẽ nạp lại")


@asset(
    deps=[raw_events],
    group_name="pipeline",
    description="silver.* và dbt_work.* — dbt build, gồm cả 78 data test và 3 unit test. "
                "Test đỏ thì dừng ở đây, feature.* chưa bị đụng.",
)
def dbt_models(context: AssetExecutionContext) -> None:
    _chay_script(context, "-m", "scripts.run_dbt", "build")


@asset(
    deps=[dbt_models],
    group_name="pipeline",
    description="feature.* — bảng agent đọc. DELETE + INSERT cả ba bảng trong MỘT "
                "transaction, chạy bằng role dbt_transformer (không có quyền DDL).",
)
def gold_tables(context: AssetExecutionContext) -> None:
    # ponytail: chưa giới hạn chạy đồng thời. Hai lần chạy chồng nhau thì `dbt build`
    # của lần này DROP bảng dbt_work mà lần kia đang publish. Một người dùng thì chưa
    # xảy ra; đặt pool limit=1 cho CẢ dbt_models lẫn gold_tables khi có lịch chạy.
    _chay_script(context, "-m", "scripts.publish_gold")


# Bấm tay: dựng lại toàn bộ bộ dữ liệu thử nghiệm từ số không.
dev_seed_job = define_asset_job(
    "dev_seed_job",
    selection=AssetSelection.assets(raw_events, dbt_models, gold_tables),
    description="Xoá và sinh lại dữ liệu mock, rồi tính lại gold. CHỈ bấm tay.",
)

# Sẽ hẹn giờ: chỉ tính lại từ raw có sẵn. Cố ý KHÔNG có raw_events.
nightly_job = define_asset_job(
    "nightly_job",
    selection=AssetSelection.assets(dbt_models, gold_tables),
    description="Tính lại gold từ raw đang có. Không bao giờ đụng tới raw.",
)

defs = Definitions(
    assets=[raw_events, dbt_models, gold_tables],
    jobs=[dev_seed_job, nightly_job],
)
