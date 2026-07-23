"""Sinh data/semantic_layer.yaml từ feature_spec + feature_describer.

Chạy lại mỗi khi sửa từ điển trong feature_describer (mục 3: một entry sửa cho
mọi feature dùng token đó). KHÔNG sửa tay file YAML.

Cách chạy (từ thư mục backend/):
    python -m scripts.generate_semantic_layer
"""
from __future__ import annotations

import os
import sys

import yaml

# Cho phép chạy trực tiếp bằng `python -m scripts.generate_semantic_layer`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings
from app.semantic.feature_describer import describe
from app.semantic.feature_spec import GROUPS, TABLES, all_features


def _support_status(name: str) -> str:
    if "nvso" in name or "_wo_" in name:
        return "needs_review"
    return "queryable"


def build() -> dict:
    features = []
    for feat in all_features():
        desc_vi, desc_en, keywords = describe(feat)
        features.append({
            "name": feat.name,
            "table": feat.table,
            "business_unit": "GSM" if feat.table.endswith("gsm_transaction") else "VINFAST",
            "group": feat.group,
            "dtype": feat.dtype,
            "aggregation": feat.agg,
            "window": feat.window,
            "unit": feat.unit,
            "null_meaning": feat.null_meaning_key,
            "description_vi": desc_vi,
            "description_en": desc_en,
            "keywords": keywords,   # gộp cả VI lẫn EN
            "support_status": _support_status(feat.name),
            "is_queryable": True,
            "is_active": True,
        })
    return {
        "meta": {
            "tables": TABLES,
            "groups": GROUPS,
            "feature_count": len(features),
            "note": "Sinh tự động — KHÔNG sửa tay. Nguồn: app/semantic/feature_spec.py + feature_describer.py",
        },
        "features": features,
    }


def main() -> None:
    settings = get_settings()
    out_path = settings.semantic_layer_path
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    data = build()
    with open(out_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False, width=120)
    print(f"Generated {data['meta']['feature_count']} features -> {out_path}")


if __name__ == "__main__":
    main()
