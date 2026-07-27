"""Chiếu YAML (authoritative) vào metadata.feature_catalog + feature_synonyms.

Source of truth = data/semantic_layer.yaml (sinh bởi generate_semantic_layer).
Script này copy YAML vào DB catalog để agent đọc lúc chạy (retriever.load_from_db).
Rebuild idempotent: xóa feature không còn trong YAML; cột vật lý vẫn giữ.

Chạy `generate_semantic_layer` TRƯỚC. Cross-check tên YAML == feature_spec để bắt
YAML cũ (quên regenerate sau khi sửa describer/spec).
"""
from __future__ import annotations

import yaml
from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine
from app.semantic.feature_spec import feature_names

UPSERT_FEATURE = text("""
INSERT INTO metadata.feature_catalog
 (feature_name, table_schema, table_name, business_unit, feature_group,
  description_vi, description_en, data_type, aggregation_type, time_window,
  null_meaning, unit, sensitivity_level, is_queryable, is_active)
VALUES
 (:feature_name, :table_schema, :table_name, :business_unit, :feature_group,
  :description_vi, :description_en, :data_type, :aggregation_type, :time_window,
  :null_meaning, :unit, :sensitivity_level, :is_queryable, TRUE)
ON CONFLICT (feature_name) DO UPDATE SET
 table_schema=EXCLUDED.table_schema, table_name=EXCLUDED.table_name,
 business_unit=EXCLUDED.business_unit, feature_group=EXCLUDED.feature_group,
 description_vi=EXCLUDED.description_vi, description_en=EXCLUDED.description_en,
 data_type=EXCLUDED.data_type, aggregation_type=EXCLUDED.aggregation_type,
 time_window=EXCLUDED.time_window, null_meaning=EXCLUDED.null_meaning,
 unit=EXCLUDED.unit, sensitivity_level=EXCLUDED.sensitivity_level,
 is_queryable=EXCLUDED.is_queryable, is_active=TRUE, updated_at=CURRENT_TIMESTAMP
RETURNING feature_id
""")


def _load_yaml_features() -> list[dict]:
    with open(get_settings().semantic_layer_path, "r", encoding="utf-8") as fh:
        features = (yaml.safe_load(fh) or {}).get("features", [])
    stale = {f["name"] for f in features} ^ feature_names()
    if stale:
        raise RuntimeError(
            "semantic_layer.yaml lệch feature_spec — chạy generate_semantic_layer trước. "
            f"Lệch: {sorted(stale)[:5]}"
        )
    return features


def seed() -> tuple[int, int]:
    features = _load_yaml_features()
    names = [f["name"] for f in features]
    synonym_count = 0
    with get_engine().begin() as conn:
        # Rebuild: xóa catalog row không còn trong YAML ⇒ catalog == YAML.
        # Cột vật lý vẫn giữ (an toàn dữ liệu); synonyms cascade theo FK.
        conn.execute(
            text("""
                DELETE FROM metadata.feature_catalog
                WHERE table_schema='feature'
                  AND table_name IN ('gsm_transaction', 'vinfast_transaction')
                  AND NOT (feature_name = ANY(:names))
            """),
            {"names": names},
        )
        for f in features:
            schema, table = f["table"].split(".", 1)
            restricted = f.get("support_status") != "queryable"
            feature_id = conn.execute(UPSERT_FEATURE, {
                "feature_name": f["name"], "table_schema": schema, "table_name": table,
                "business_unit": f["business_unit"],
                "feature_group": f["group"], "description_vi": f["description_vi"],
                "description_en": f.get("description_en", ""), "data_type": f["dtype"],
                "aggregation_type": f.get("aggregation"), "time_window": f.get("window"),
                "null_meaning": f.get("null_meaning"), "unit": f.get("unit"),
                "sensitivity_level": "restricted" if restricted else "internal",
                "is_queryable": not restricted,
            }).scalar_one()
            conn.execute(text("DELETE FROM metadata.feature_synonyms WHERE feature_id=:id"), {"id": feature_id})
            rows = []
            for keyword in sorted(set(f.get("keywords", []))):
                if len(keyword) <= 200:
                    lang = "vi" if any(ord(c) > 127 for c in keyword) else "en"
                    rows.append({"id": feature_id, "text": keyword, "lang": lang})
            if rows:
                conn.execute(text("""
                    INSERT INTO metadata.feature_synonyms
                      (feature_id, synonym_text, language_code, synonym_type)
                    VALUES (:id, :text, :lang, 'business')
                """), rows)
                synonym_count += len(rows)
    return len(features), synonym_count


def main() -> None:
    features, synonyms = seed()
    print(f"Seeded metadata from YAML: features={features}, synonyms={synonyms}")


if __name__ == "__main__":
    main()
