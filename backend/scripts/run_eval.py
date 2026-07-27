"""Chạy golden set + in báo cáo execution accuracy theo tầng/category.

  python -m scripts.run_eval --tag baseline
Đổi prompt/retriever rồi chạy lại --tag after để so before/after. LLM-optional:
thiếu LLM_API_KEY → chỉ đo retrieval + refusal + gold_sql (bỏ execution accuracy).
"""
from __future__ import annotations

import argparse

from app.eval.evaluator import evaluate, format_report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="baseline", help="nhãn run (lưu vào query_test_run.retriever_version)")
    ap.add_argument("--split", default="dev", choices=["dev", "holdout", "all"],
                    help="dev (tune) | holdout (đo cuối, phải khóa trước) | all")
    args = ap.parse_args()
    print(format_report(evaluate(args.tag, args.split)))


if __name__ == "__main__":
    main()
