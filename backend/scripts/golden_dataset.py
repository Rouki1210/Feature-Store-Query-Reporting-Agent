"""Governance golden set (Task 1.4): export dev/holdout, khóa holdout, coverage.

  python -m scripts.golden_dataset build     # xuất jsonl + coverage report (derived, an toàn regen)
  python -m scripts.golden_dataset lock      # khóa checksum holdout (chống leakage)
  python -m scripts.golden_dataset verify    # kiểm holdout chưa bị sửa sau khi khóa

Holdout được khóa TRƯỚC khi tune. `verify` fail (exit 1) nếu nội dung holdout đổi.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import date

from app.config import get_settings
from app.eval.golden import (
    holdout_checksum,
    load_golden_cases,
    split_cases,
    validate_cases,
)

_DATA = os.path.dirname(get_settings().golden_set_path) or "."
_REPORTS = os.path.join(os.path.dirname(_DATA) or ".", "reports")
DEV_JSONL = os.path.join(_DATA, "golden_queries_dev.jsonl")
HOLDOUT_JSONL = os.path.join(_DATA, "golden_queries_holdout.jsonl")
CHECKSUM_FILE = os.path.join(_DATA, "HOLDOUT_CHECKSUM")
VERSION_FILE = os.path.join(_DATA, "HOLDOUT_VERSION")
COVERAGE_MD = os.path.join(_REPORTS, "golden_dataset_coverage.md")


def _write_jsonl(path: str, cases: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for c in cases:
            fh.write(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n")


def build() -> None:
    cases = load_golden_cases()
    errors = validate_cases(cases)
    if errors:
        raise RuntimeError("golden_set.yaml lỗi:\n  " + "\n  ".join(errors))
    dev, hold = split_cases()
    _write_jsonl(DEV_JSONL, dev)
    _write_jsonl(HOLDOUT_JSONL, hold)
    os.makedirs(_REPORTS, exist_ok=True)
    _write_coverage(cases, dev, hold)
    print(f"build: dev={len(dev)} holdout={len(hold)} -> {DEV_JSONL}, {HOLDOUT_JSONL}, {COVERAGE_MD}")


def lock(relock: bool = False) -> None:
    current = holdout_checksum()
    if os.path.exists(CHECKSUM_FILE) and not relock:
        stored = open(CHECKSUM_FILE, encoding="utf-8").read().strip()
        if stored != current:
            raise SystemExit(
                "HOLDOUT đã đổi so với bản khóa. Nếu CỐ Ý cập nhật benchmark, chạy: "
                "golden_dataset lock --relock (và ghi lý do)."
            )
        print("lock: holdout khớp checksum đã khóa — không đổi.")
        return
    version = 1
    if os.path.exists(VERSION_FILE):
        try:
            version = int(open(VERSION_FILE, encoding="utf-8").read().split()[0]) + 1
        except Exception:
            version = 1
    with open(CHECKSUM_FILE, "w", encoding="utf-8") as fh:
        fh.write(current + "\n")
    with open(VERSION_FILE, "w", encoding="utf-8") as fh:
        fh.write(f"{version}  locked={date.today().isoformat()}\n")
    print(f"lock: HOLDOUT v{version} khóa với checksum {current[:12]}...")


def verify() -> None:
    if not os.path.exists(CHECKSUM_FILE):
        raise SystemExit("verify: chưa khóa holdout — chạy `golden_dataset lock` trước.")
    stored = open(CHECKSUM_FILE, encoding="utf-8").read().strip()
    current = holdout_checksum()
    if stored != current:
        raise SystemExit(f"verify: HOLDOUT ĐÃ ĐỔI (benchmark leakage!)\n stored={stored[:16]}\n now   ={current[:16]}")
    print(f"verify: holdout nguyên vẹn ({current[:12]}...).")


def _write_coverage(cases: list[dict], dev: list[dict], hold: list[dict]) -> None:
    by = lambda cs, key: Counter(c.get(key) for c in cs)
    diff_d, diff_h = by(dev, "difficulty"), by(hold, "difficulty")
    cat_d, cat_h = by(dev, "category"), by(hold, "category")
    bus = by(cases, "expected_business_unit")
    cross_bu = [c["code"] for c in cases if c.get("expected_business_unit") not in (None, "GSM", "VINFAST")]
    lines = [
        "# Golden dataset coverage (Task 1.4)", "",
        f"- Tổng: **{len(cases)}** case — dev **{len(dev)}**, holdout **{len(hold)}** (disjoint).",
        f"- Holdout checksum: `{holdout_checksum()[:16]}...`",
        f"- Cross-BU trong benchmark: **{len(cross_bu)}** {'(OK)' if not cross_bu else cross_bu}",
        "",
        "## Theo độ khó (dev / holdout)", "",
        "| difficulty | dev | holdout |", "|---|---:|---:|",
    ]
    for d in ("easy", "medium", "hard"):
        lines.append(f"| {d} | {diff_d.get(d,0)} | {diff_h.get(d,0)} |")
    lines += ["", "## Theo category (mục đích) (dev / holdout)", "",
              "| category | dev | holdout |", "|---|---:|---:|"]
    for cat in sorted(set(cat_d) | set(cat_h)):
        lines.append(f"| {cat} | {cat_d.get(cat,0)} | {cat_h.get(cat,0)} |")
    lines += ["", "## Theo Business Unit (toàn tập)", "",
              "| BU | count |", "|---|---:|"]
    for k, v in bus.items():
        lines.append(f"| {k or '(guardrail/none)'} | {v} |")
    lines.append("")
    with open(COVERAGE_MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["build", "lock", "verify"])
    ap.add_argument("--relock", action="store_true", help="cố ý cập nhật khóa holdout")
    args = ap.parse_args()
    if args.action == "build":
        build()
    elif args.action == "lock":
        lock(args.relock)
    else:
        verify()


if __name__ == "__main__":
    main()
