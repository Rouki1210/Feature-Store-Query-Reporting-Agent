"""Nạp + kiểm tra golden set (nguồn chung cho seeder / evaluator / test integrity).

golden_set.yaml là authoritative. validate_cases() bắt lỗi tĩnh trước khi seed/chạy:
enum hợp lệ, code duy nhất, expected_features ⊆ canonical 353, gold_sql qua guard.
"""
from __future__ import annotations

import hashlib
import json
import os

from app.agent.contracts import RefusalCode
from app.semantic.feature_spec import feature_names
from app.sql.guards import GuardError, validate_sql

DIFFICULTY = {"easy", "medium", "hard"}
CATEGORY = {
    # Sprint 1
    "single_feature", "time_comparison", "service_breakdown", "ambiguous_question",
    "out_of_scope", "restricted_data", "sql_safety",
    # Sprint 2 — docs/sprint2_definition_of_done.md §3.
    # `multi_turn` CỐ Ý không có ở đây: evaluator gọi thẳng pipeline (stateless), đo
    # hội thoại phải qua `ask_with_context` nên nằm ở tests/test_multi_turn.py.
    "cross_bu", "buyer_vs_owner", "point_in_time", "join_safety",
    # Golden set Sprint 2 v2: taxonomy benchmark mở rộng. Metadata này được giữ
    # nguyên cả khi evaluator hiện tại chưa chấm riêng visualization/multi-turn.
    "insufficient_data", "semantic_clarification", "short_term_state", "visualization",
}
STATUS = {"ok", "clarify", "out_of_scope", "error"}
REFUSAL = {c.value for c in RefusalCode} | {"insufficient_feature", None}
_PROJECTION_COLUMNS = {"customer_id", "snapshot_date"}


def load_golden(path: str | None = None) -> dict:
    """Nạp toàn bộ golden_set.yaml: {cases: [...], holdout: [codes]}."""
    import yaml

    from app.config import get_settings

    path = path or get_settings().golden_set_path
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_golden_cases(path: str | None = None) -> list[dict]:
    return load_golden(path).get("cases", [])


def split_cases(path: str | None = None) -> tuple[list[dict], list[dict]]:
    """Trả (dev, holdout) theo `splits.holdout` v2 hoặc `holdout` legacy."""
    data = load_golden(path)
    holdout_codes = set((data.get("splits") or {}).get("holdout") or data.get("holdout") or [])
    dev, hold = [], []
    for c in data.get("cases", []):
        (hold if c.get("code") in holdout_codes else dev).append(c)
    return dev, hold


def cases_for_split(split: str, path: str | None = None) -> list[dict]:
    dev, hold = split_cases(path)
    return {"dev": dev, "holdout": hold, "all": dev + hold}[split]


def _case_digest(case: dict) -> str:
    """Chữ ký ổn định của 1 case (các trường ảnh hưởng kết quả eval)."""
    payload = {
        k: case.get(k)
        for k in ("code", "question_vi", "difficulty", "category",
                  "expected_business_unit", "expected_status", "expected_refusal", "gold_sql")
    }
    payload["expected_features"] = sorted(case.get("expected_features") or [])
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def holdout_checksum(path: str | None = None) -> str:
    """SHA256 trên nội dung các holdout case (sort theo code) — dùng để khóa."""
    _, hold = split_cases(path)
    blob = "\n".join(_case_digest(c) for c in sorted(hold, key=lambda x: x["code"]))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def checksum_file(path: str | None = None) -> str:
    from app.config import get_settings

    base = path or get_settings().golden_set_path
    return os.path.join(os.path.dirname(base) or ".", "HOLDOUT_CHECKSUM")


def assert_holdout_unchanged(path: str | None = None) -> str:
    """Gate chống leakage: đo holdout BẮT BUỘC đã khóa & nguyên vẹn, nếu không → raise.

    - Chưa khóa → raise (không cho đo holdout khi chưa lock — nếu không gate vô nghĩa).
    - Đã khóa nhưng nội dung đổi → raise (benchmark leakage).
    """
    cf = checksum_file(path)
    if not os.path.exists(cf):
        raise RuntimeError(
            "HOLDOUT chưa khóa — không được đo holdout khi chưa lock. "
            "Chạy `python -m scripts.golden_dataset lock` trước."
        )
    stored = open(cf, encoding="utf-8").read().strip()
    if stored != holdout_checksum(path):
        raise RuntimeError("HOLDOUT đã đổi sau khi khóa — benchmark leakage! Xem `golden_dataset verify`.")
    return "✔ holdout đã khóa & nguyên vẹn."


def validate_cases(cases: list[dict]) -> list[str]:
    """Trả về danh sách lỗi (rỗng = hợp lệ). Không raise — caller quyết định."""
    errors: list[str] = []
    canonical = frozenset(feature_names()) | _PROJECTION_COLUMNS
    seen: set[str] = set()
    for c in cases:
        code = c.get("code")
        if not code:
            errors.append("Thiếu 'code' ở một case.")
            continue
        if code in seen:
            errors.append(f"{code}: code trùng.")
        seen.add(code)
        if c.get("difficulty") not in DIFFICULTY:
            errors.append(f"{code}: difficulty không hợp lệ ({c.get('difficulty')}).")
        if c.get("category") not in CATEGORY:
            errors.append(f"{code}: category không hợp lệ ({c.get('category')}).")
        if c.get("expected_status") not in STATUS:
            errors.append(f"{code}: expected_status không hợp lệ ({c.get('expected_status')}).")
        if c.get("expected_refusal") not in REFUSAL:
            errors.append(f"{code}: expected_refusal không hợp lệ ({c.get('expected_refusal')}).")
        bad = set(c.get("expected_features") or []) - canonical
        if bad:
            errors.append(f"{code}: expected_features ngoài canonical 353: {sorted(bad)}.")
        gold_sql = c.get("gold_sql")
        if gold_sql:
            try:
                validate_sql(gold_sql)
            except GuardError as exc:
                errors.append(f"{code}: gold_sql không qua guard: {exc}")
        # answerable phải có gold_sql; guardrail (status != ok) thì gold_sql null.
        if c.get("expected_status") == "ok" and not gold_sql:
            errors.append(f"{code}: expected_status=ok nhưng thiếu gold_sql.")
    return errors
