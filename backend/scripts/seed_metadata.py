"""Chiếu YAML (authoritative) vào metadata.feature_catalog + feature_synonyms.

Source of truth = data/semantic_layer.yaml (sinh bởi generate_semantic_layer).
Script này copy YAML vào DB catalog để agent đọc lúc chạy (retriever.load_from_db).
Rebuild idempotent: xóa feature không còn trong YAML; cột vật lý vẫn giữ.

Chạy `generate_semantic_layer` TRƯỚC. Cross-check tên YAML == feature_spec để bắt
YAML cũ (quên regenerate sau khi sửa describer/spec).
"""
from __future__ import annotations

import json
import yaml
from sqlalchemy import text

from app.agent.breakdown import DEFAULT_BREAKDOWNS
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
                  AND table_name IN ('gsm_transaction', 'vinfast_transaction',
                                     'customer_cross_bu_feature')
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


def seed_join_catalog() -> int:
    """Chiếu `DEFAULT_RULES` của Join Planner vào `metadata.join_catalog`.

    Nguồn sự thật là DB (docs/join_policy.md §6); `DEFAULT_RULES` chỉ là bản seed +
    fallback khi chưa có DB. Rebuild idempotent: dòng không còn trong DEFAULT_RULES
    bị tắt (`is_active=FALSE`) chứ không xóa, để còn truy vết log cũ.
    """
    from app.agent.join_planner import DEFAULT_RULES

    with get_engine().begin() as conn:
        # Tắt hết rồi bật lại theo DEFAULT_RULES. Cách này thay cho so sánh row-value
        # `(left,right) <> ALL(:pairs)` — psycopg không truyền được mảng tuple
        # ("input of anonymous composite types is not implemented").
        conn.execute(text("UPDATE metadata.join_catalog SET is_active = FALSE"))
        for rule in DEFAULT_RULES:
            conn.execute(text("""
                INSERT INTO metadata.join_catalog
                  (left_table, right_table, join_keys, join_type, cardinality,
                   requires_snapshot_key, allowed_intents, explanation_vi, is_active)
                VALUES (:left, :right, :keys, :type, :card, :snap, :intents, :why, TRUE)
                ON CONFLICT (left_table, right_table) DO UPDATE SET
                  join_keys=EXCLUDED.join_keys, join_type=EXCLUDED.join_type,
                  cardinality=EXCLUDED.cardinality,
                  requires_snapshot_key=EXCLUDED.requires_snapshot_key,
                  allowed_intents=EXCLUDED.allowed_intents,
                  explanation_vi=EXCLUDED.explanation_vi, is_active=TRUE
            """), {
                "left": rule.left_table, "right": rule.right_table,
                "keys": list(rule.join_keys), "type": rule.join_type,
                "card": rule.cardinality, "snap": rule.requires_snapshot_key,
                "intents": list(rule.allowed_intents), "why": rule.explanation_vi,
            })
    return len(DEFAULT_RULES)


def seed_breakdown_catalog() -> int:
    """Đồng bộ registry khai báo; không lưu biểu thức SQL tự do."""
    with get_engine().begin() as conn:
        conn.execute(text("UPDATE metadata.breakdown_catalog SET is_active = FALSE"))
        for spec in DEFAULT_BREAKDOWNS:
            data = spec.as_catalog_dict()
            conn.execute(text("""
                INSERT INTO metadata.breakdown_catalog
                  (dimension_key, label_vi, aliases, strategy, source_tables, members,
                   compatible_dimensions, overlap_possible, is_active)
                VALUES (:key, :label, :aliases, :strategy, :tables, CAST(:members AS jsonb),
                        :compatible, :overlap, TRUE)
                ON CONFLICT (dimension_key) DO UPDATE SET
                  label_vi=EXCLUDED.label_vi, aliases=EXCLUDED.aliases,
                  strategy=EXCLUDED.strategy, source_tables=EXCLUDED.source_tables,
                  members=EXCLUDED.members,
                  compatible_dimensions=EXCLUDED.compatible_dimensions,
                  overlap_possible=EXCLUDED.overlap_possible, is_active=TRUE,
                  updated_at=CURRENT_TIMESTAMP
            """), {
                "key": data["dimension_key"], "label": data["label_vi"],
                "aliases": data["aliases"], "strategy": data["strategy"],
                "tables": data["source_tables"],
                "members": json.dumps(data["members"], ensure_ascii=False),
                "compatible": data["compatible_dimensions"],
                "overlap": data["overlap_possible"],
            })
    return len(DEFAULT_BREAKDOWNS)


def main() -> None:
    features, synonyms = seed()
    joins = seed_join_catalog()
    breakdowns = seed_breakdown_catalog()
    print(
        "Seeded metadata from YAML: "
        f"features={features}, synonyms={synonyms}, joins={joins}, breakdowns={breakdowns}"
    )


if __name__ == "__main__":
    main()
