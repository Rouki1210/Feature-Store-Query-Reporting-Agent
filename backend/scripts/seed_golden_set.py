"""Chiếu golden_set.yaml (authoritative) vào eval.query_test_case.

Rebuild idempotent: xóa case không còn trong YAML; upsert theo test_case_code.
Cross-check tĩnh (enum/canonical/guard) trước khi ghi — fail-fast.
Chạy:  python -m scripts.seed_golden_set
"""
from __future__ import annotations

import json

from sqlalchemy import text

from app.db import get_engine
from app.eval.golden import load_golden_cases, validate_cases

UPSERT = text("""
INSERT INTO eval.query_test_case
 (test_case_code, question_vi, expected_business_unit, expected_features,
  expected_sql, difficulty_level, test_category, tolerance_config, notes, is_active)
VALUES
 (:code, :q, :bu, CAST(:features AS jsonb), :sql, :difficulty, :category,
  CAST(:tol AS jsonb), :notes, TRUE)
ON CONFLICT (test_case_code) DO UPDATE SET
 question_vi=EXCLUDED.question_vi, expected_business_unit=EXCLUDED.expected_business_unit,
 expected_features=EXCLUDED.expected_features, expected_sql=EXCLUDED.expected_sql,
 difficulty_level=EXCLUDED.difficulty_level, test_category=EXCLUDED.test_category,
 tolerance_config=EXCLUDED.tolerance_config, notes=EXCLUDED.notes,
 is_active=TRUE, updated_at=CURRENT_TIMESTAMP
""")


def seed() -> int:
    cases = load_golden_cases()
    errors = validate_cases(cases)
    if errors:
        raise RuntimeError("golden_set.yaml không hợp lệ:\n  " + "\n  ".join(errors))
    codes = [c["code"] for c in cases]
    with get_engine().begin() as conn:
        # Case không còn trong YAML: DEACTIVATE (is_active=FALSE), KHÔNG xóa —
        # giữ nguyên lịch sử đánh giá trong query_test_run (tránh data-loss + né FK).
        # Case quay lại YAML sẽ được upsert bật lại is_active=TRUE.
        conn.execute(
            text("""
                UPDATE eval.query_test_case SET is_active=FALSE, updated_at=CURRENT_TIMESTAMP
                WHERE NOT (test_case_code = ANY(:codes))
            """),
            {"codes": codes},
        )
        for c in cases:
            # Trường ngoài cột chuẩn (expected_status/refusal/needs_llm/float_abs) gộp vào
            # tolerance_config để row DB tự chứa đủ — evaluator vẫn đọc YAML là chính.
            tol = {
                "float_abs": (c.get("tolerance") or {}).get("float_abs", 0.01),
                "expected_status": c.get("expected_status"),
                "expected_refusal": c.get("expected_refusal"),
                "needs_llm": bool(c.get("needs_llm", False)),
                "purpose": c.get("purpose"),
            }
            conn.execute(UPSERT, {
                "code": c["code"], "q": c["question_vi"],
                "bu": c.get("expected_business_unit"),
                "features": json.dumps(c.get("expected_features") or []),
                "sql": c.get("gold_sql"), "difficulty": c["difficulty"],
                "category": c["category"], "tol": json.dumps(tol, ensure_ascii=False),
                "notes": c.get("purpose"),
            })
    return len(cases)


def main() -> None:
    n = seed()
    print(f"Seeded golden set: {n} cases -> eval.query_test_case")


if __name__ == "__main__":
    main()
