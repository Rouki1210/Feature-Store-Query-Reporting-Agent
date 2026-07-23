"""Idempotently seed metadata.feature_catalog and feature_synonyms."""
from __future__ import annotations

from sqlalchemy import text

from app.db import get_engine
from app.semantic.feature_describer import describe
from app.semantic.feature_spec import all_features

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


def seed() -> tuple[int, int]:
    features = all_features()
    synonym_count = 0
    with get_engine().begin() as conn:
        # Keep physical legacy columns for data safety, but remove them from
        # retrieval/SQL generation. Canonical inventory below re-enables only
        # retained features.
        conn.execute(text("""
            UPDATE metadata.feature_catalog
            SET is_queryable=FALSE, is_active=FALSE, updated_at=CURRENT_TIMESTAMP
            WHERE table_schema='feature'
              AND table_name IN ('gsm_transaction', 'vinfast_transaction')
        """))
        for feat in features:
            vi, en, keywords = describe(feat)
            schema, table = feat.table.split(".", 1)
            needs_review = "nvso" in feat.name or "_wo_" in feat.name
            feature_id = conn.execute(UPSERT_FEATURE, {
                "feature_name": feat.name, "table_schema": schema, "table_name": table,
                "business_unit": "GSM" if table.startswith("gsm") else "VINFAST",
                "feature_group": feat.group, "description_vi": vi, "description_en": en,
                "data_type": feat.dtype, "aggregation_type": feat.agg,
                "time_window": feat.window, "null_meaning": feat.null_meaning_key,
                "unit": feat.unit,
                "sensitivity_level": "restricted" if needs_review else "internal",
                "is_queryable": not needs_review,
            }).scalar_one()
            conn.execute(text("DELETE FROM metadata.feature_synonyms WHERE feature_id=:id"), {"id": feature_id})
            rows = []
            for keyword in sorted(set(keywords)):
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
    print(f"Seeded metadata: features={features}, synonyms={synonyms}")


if __name__ == "__main__":
    main()
