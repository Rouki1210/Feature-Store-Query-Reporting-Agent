-- ============================================================================
-- FEATURE STORE QUERY & REPORTING AGENT
-- SPRINT 1 DATABASE SCHEMA
-- Target: PostgreSQL 14+
--
-- Sprint 1 scope:
--   1) Raw/mock data for GSM and VinFast
--   2) Feature tables by Business Unit
--   3) Metadata and ontology for retrieval
--   4) Query/audit logging
--   5) SQL validation logging
--   6) Query accuracy test dataset and test runs
--
-- Important limitations:
--   - The agent must NOT read schema raw directly.
--   - vinfast_orders.status is the current source status only.
--   - Sprint 1 must NOT claim that a customer is a vehicle owner.
--   - Point-in-time order status history and vehicle handover are Sprint 2.
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- 0. SCHEMAS
-- ----------------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS feature;
CREATE SCHEMA IF NOT EXISTS metadata;
CREATE SCHEMA IF NOT EXISTS agent;
CREATE SCHEMA IF NOT EXISTS eval;

-- ----------------------------------------------------------------------------
-- 1. RAW DATA LAYER
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS raw.customers (
    customer_id           BIGINT PRIMARY KEY,
    created_at            TIMESTAMPTZ NOT NULL,
    updated_at            TIMESTAMPTZ NOT NULL,

    gender                VARCHAR(20),
    birth_date            DATE,
    register_channel      VARCHAR(50),
    residence_province    VARCHAR(100),
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,

    source_system         VARCHAR(50),
    ingested_at           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_customers_gender
        CHECK (
            gender IS NULL
            OR gender IN ('male', 'female', 'other', 'unknown')
        ),

    CONSTRAINT chk_customers_updated_at
        CHECK (updated_at >= created_at)
);

COMMENT ON TABLE raw.customers IS
'Customer master used as the shared customer_id across GSM and VinFast. Sensitive PII must be stored outside the agent-accessible schemas.';

CREATE INDEX IF NOT EXISTS idx_customers_active
    ON raw.customers (is_active);

CREATE INDEX IF NOT EXISTS idx_customers_created_at
    ON raw.customers (created_at);


CREATE TABLE IF NOT EXISTS raw.date_dim (
    date_id               DATE PRIMARY KEY,

    day_of_week           SMALLINT NOT NULL,
    day_name              VARCHAR(20) NOT NULL,
    day_of_month          SMALLINT NOT NULL,
    week_of_month         SMALLINT,
    week_of_year          SMALLINT NOT NULL,

    month_number          SMALLINT NOT NULL,
    month_name            VARCHAR(20) NOT NULL,
    quarter_number        SMALLINT NOT NULL,
    year_number           INTEGER NOT NULL,

    is_weekend            BOOLEAN NOT NULL DEFAULT FALSE,
    is_holiday            BOOLEAN NOT NULL DEFAULT FALSE,
    holiday_name          VARCHAR(200),

    CONSTRAINT chk_date_dim_day_of_week
        CHECK (day_of_week BETWEEN 1 AND 7),

    CONSTRAINT chk_date_dim_day_of_month
        CHECK (day_of_month BETWEEN 1 AND 31),

    CONSTRAINT chk_date_dim_week_of_month
        CHECK (week_of_month IS NULL OR week_of_month BETWEEN 1 AND 6),

    CONSTRAINT chk_date_dim_week_of_year
        CHECK (week_of_year BETWEEN 1 AND 53),

    CONSTRAINT chk_date_dim_month
        CHECK (month_number BETWEEN 1 AND 12),

    CONSTRAINT chk_date_dim_quarter
        CHECK (quarter_number BETWEEN 1 AND 4)
);

COMMENT ON TABLE raw.date_dim IS
'Calendar dimension used for daily snapshots, time windows and reporting periods.';


CREATE TABLE IF NOT EXISTS raw.gsm_trips (
    trip_id               BIGINT PRIMARY KEY,
    customer_id           BIGINT NOT NULL
                          REFERENCES raw.customers(customer_id),

    trip_start_time       TIMESTAMPTZ NOT NULL,
    trip_end_time         TIMESTAMPTZ,

    service_type          VARCHAR(30) NOT NULL,
    distance_km           NUMERIC(12,2),
    duration_min          INTEGER,

    total_fare            NUMERIC(18,2) NOT NULL,
    discount_amount       NUMERIC(18,2) NOT NULL DEFAULT 0,
    paid_amount           NUMERIC(18,2),

    payment_method        VARCHAR(30),
    status                VARCHAR(20) NOT NULL,

    created_at            TIMESTAMPTZ NOT NULL,
    updated_at            TIMESTAMPTZ NOT NULL,
    ingested_at           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_gsm_trips_service_type
        CHECK (
            service_type IN ('taxi', 'bike', 'express', 'food', 'other')
        ),

    CONSTRAINT chk_gsm_trips_status
        CHECK (
            status IN (
                'created',
                'accepted',
                'in_progress',
                'completed',
                'cancelled'
            )
        ),

    CONSTRAINT chk_gsm_trips_distance
        CHECK (distance_km IS NULL OR distance_km >= 0),

    CONSTRAINT chk_gsm_trips_duration
        CHECK (duration_min IS NULL OR duration_min >= 0),

    CONSTRAINT chk_gsm_trips_amounts
        CHECK (
            total_fare >= 0
            AND discount_amount >= 0
            AND (paid_amount IS NULL OR paid_amount >= 0)
        ),

    CONSTRAINT chk_gsm_trips_time
        CHECK (
            trip_end_time IS NULL
            OR trip_end_time >= trip_start_time
        ),

    CONSTRAINT chk_gsm_trips_update_time
        CHECK (updated_at >= created_at)
);

COMMENT ON TABLE raw.gsm_trips IS
'One row per GSM trip. Source for GSM feature generation only; the agent must not query this table directly.';

CREATE INDEX IF NOT EXISTS idx_gsm_trips_customer_start
    ON raw.gsm_trips (customer_id, trip_start_time);

CREATE INDEX IF NOT EXISTS idx_gsm_trips_status_start
    ON raw.gsm_trips (status, trip_start_time);

CREATE INDEX IF NOT EXISTS idx_gsm_trips_service_start
    ON raw.gsm_trips (service_type, trip_start_time);


CREATE TABLE IF NOT EXISTS raw.vinfast_orders (
    order_id              BIGINT PRIMARY KEY,
    customer_id           BIGINT NOT NULL
                          REFERENCES raw.customers(customer_id),

    created_at            TIMESTAMPTZ NOT NULL,
    updated_at            TIMESTAMPTZ NOT NULL,

    status                VARCHAR(30) NOT NULL,
    order_type            VARCHAR(30) NOT NULL,

    list_price            NUMERIC(18,2) NOT NULL,
    paid_amount           NUMERIC(18,2) NOT NULL,

    discount_amount       NUMERIC(18,2)
                          GENERATED ALWAYS AS
                          (list_price - paid_amount) STORED,

    has_discount          BOOLEAN
                          GENERATED ALWAYS AS
                          (list_price > paid_amount) STORED,

    battery_kwh           NUMERIC(10,2),
    vehicle_model         VARCHAR(50),

    source_system         VARCHAR(50),
    ingested_at           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_vinfast_orders_status
        CHECK (
            status IN (
                'created',
                'processing',
                'completed',
                'cancelled',
                'delivered'
            )
        ),

    CONSTRAINT chk_vinfast_orders_type
        CHECK (
            order_type IN (
                'vehicle',
                'accessories',
                'work_order',
                'nvso'
            )
        ),

    CONSTRAINT chk_vinfast_orders_amounts
        CHECK (
            list_price >= 0
            AND paid_amount >= 0
            AND paid_amount <= list_price
        ),

    CONSTRAINT chk_vinfast_orders_battery
        CHECK (
            order_type = 'vehicle'
            OR battery_kwh IS NULL
        ),

    CONSTRAINT chk_vinfast_orders_update_time
        CHECK (updated_at >= created_at)
);

COMMENT ON TABLE raw.vinfast_orders IS
'One row per VinFast order. In Sprint 1, completed means completed order only; it must not be interpreted as confirmed vehicle handover or ownership.';

CREATE INDEX IF NOT EXISTS idx_vinfast_orders_customer_created
    ON raw.vinfast_orders (customer_id, created_at);

CREATE INDEX IF NOT EXISTS idx_vinfast_orders_status_updated
    ON raw.vinfast_orders (status, updated_at);

CREATE INDEX IF NOT EXISTS idx_vinfast_orders_type_created
    ON raw.vinfast_orders (order_type, created_at);


-- ----------------------------------------------------------------------------
-- 2. FEATURE LAYER
-- Grain: one row per customer_id + snapshot_date
--
-- Note:
-- The production project may contain 167 GSM features and 186 VinFast features.
-- This Sprint 1 schema defines the stable core columns and can be extended by
-- generated migrations once the final feature inventory is approved.
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS feature.gsm_transaction (
    customer_id                     BIGINT NOT NULL
                                    REFERENCES raw.customers(customer_id),

    snapshot_date                   DATE NOT NULL
                                    REFERENCES raw.date_dim(date_id),

    completed_txn_count_daily       INTEGER NOT NULL DEFAULT 0,
    completed_txn_count_l1w         INTEGER NOT NULL DEFAULT 0,
    completed_txn_count_l1m         INTEGER NOT NULL DEFAULT 0,
    completed_txn_count_l3m         INTEGER NOT NULL DEFAULT 0,
    completed_txn_count_l6m         INTEGER NOT NULL DEFAULT 0,
    completed_txn_count_l12m        INTEGER NOT NULL DEFAULT 0,

    completed_txn_amount_l1m        NUMERIC(18,2) NOT NULL DEFAULT 0,
    completed_txn_amount_l3m        NUMERIC(18,2) NOT NULL DEFAULT 0,
    completed_txn_amount_l12m       NUMERIC(18,2) NOT NULL DEFAULT 0,

    completed_distance_l1m          NUMERIC(18,2) NOT NULL DEFAULT 0,
    completed_duration_l1m          NUMERIC(18,2) NOT NULL DEFAULT 0,

    avg_ticket_l1m                  NUMERIC(18,2),
    avg_distance_l1m                NUMERIC(12,2),
    completed_rate_l1m              NUMERIC(8,4),

    taxi_completed_count_l1m        INTEGER NOT NULL DEFAULT 0,
    bike_completed_count_l1m        INTEGER NOT NULL DEFAULT 0,
    express_completed_count_l1m     INTEGER NOT NULL DEFAULT 0,
    food_completed_count_l1m        INTEGER NOT NULL DEFAULT 0,

    txn_count_l1m_vs_l3m            NUMERIC(12,4),
    txn_amount_l1m_vs_l3m           NUMERIC(12,4),
    txn_count_l3m_vs_l12m           NUMERIC(12,4),

    first_trip_date                 DATE,
    last_trip_date                  DATE,
    active_days_l1m                 INTEGER NOT NULL DEFAULT 0,
    days_since_last_trip            INTEGER,
    is_active_l1m                   BOOLEAN NOT NULL DEFAULT FALSE,

    feature_build_at                TIMESTAMPTZ NOT NULL
                                    DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (customer_id, snapshot_date),

    CONSTRAINT chk_gsm_feature_rate
        CHECK (
            completed_rate_l1m IS NULL
            OR completed_rate_l1m BETWEEN 0 AND 1
        ),

    CONSTRAINT chk_gsm_feature_non_negative_counts
        CHECK (
            completed_txn_count_daily >= 0
            AND completed_txn_count_l1w >= 0
            AND completed_txn_count_l1m >= 0
            AND completed_txn_count_l3m >= 0
            AND completed_txn_count_l6m >= 0
            AND completed_txn_count_l12m >= 0
            AND taxi_completed_count_l1m >= 0
            AND bike_completed_count_l1m >= 0
            AND express_completed_count_l1m >= 0
            AND food_completed_count_l1m >= 0
            AND active_days_l1m >= 0
        ),

    CONSTRAINT chk_gsm_feature_date_order
        CHECK (
            first_trip_date IS NULL
            OR last_trip_date IS NULL
            OR first_trip_date <= last_trip_date
        )
);

COMMENT ON TABLE feature.gsm_transaction IS
'GSM feature table. One row per customer and snapshot date. Agent-readable.';

CREATE INDEX IF NOT EXISTS idx_gsm_transaction_snapshot
    ON feature.gsm_transaction (snapshot_date);

CREATE INDEX IF NOT EXISTS idx_gsm_transaction_active
    ON feature.gsm_transaction (snapshot_date, is_active_l1m);


CREATE TABLE IF NOT EXISTS feature.vinfast_transaction (
    customer_id                           BIGINT NOT NULL
                                          REFERENCES raw.customers(customer_id),

    snapshot_date                         DATE NOT NULL
                                          REFERENCES raw.date_dim(date_id),

    order_created_count_daily             INTEGER NOT NULL DEFAULT 0,
    order_created_count_l1m               INTEGER NOT NULL DEFAULT 0,
    order_created_count_l3m               INTEGER NOT NULL DEFAULT 0,
    order_created_count_l12m              INTEGER NOT NULL DEFAULT 0,

    completed_order_count_l1m             INTEGER NOT NULL DEFAULT 0,
    completed_order_count_l3m             INTEGER NOT NULL DEFAULT 0,
    completed_order_count_l12m            INTEGER NOT NULL DEFAULT 0,

    vehicle_order_count_l1m               INTEGER NOT NULL DEFAULT 0,
    vehicle_completed_order_count_l1m     INTEGER NOT NULL DEFAULT 0,

    accessories_order_count_l1m           INTEGER NOT NULL DEFAULT 0,
    work_order_count_l1m                  INTEGER NOT NULL DEFAULT 0,
    nvso_order_count_l1m                  INTEGER NOT NULL DEFAULT 0,

    order_amount_l1m                      NUMERIC(18,2) NOT NULL DEFAULT 0,
    order_amount_l3m                      NUMERIC(18,2) NOT NULL DEFAULT 0,
    order_amount_l12m                     NUMERIC(18,2) NOT NULL DEFAULT 0,

    vehicle_amount_l1m                    NUMERIC(18,2) NOT NULL DEFAULT 0,
    accessories_amount_l1m                NUMERIC(18,2) NOT NULL DEFAULT 0,

    discount_order_count_l1m              INTEGER NOT NULL DEFAULT 0,
    discount_amount_l1m                   NUMERIC(18,2) NOT NULL DEFAULT 0,

    avg_order_value_l1m                   NUMERIC(18,2),
    avg_vehicle_order_value_l1m           NUMERIC(18,2),
    battery_kwh_sum_l1m                   NUMERIC(18,2),

    order_count_l1m_vs_l3m                NUMERIC(12,4),
    amount_l1m_vs_l3m                     NUMERIC(12,4),
    order_count_l3m_vs_l12m               NUMERIC(12,4),

    first_order_date                      DATE,
    last_order_date                       DATE,
    first_vehicle_purchase_date           DATE,
    days_since_last_order                 INTEGER,

    is_vinfast_buyer                      BOOLEAN NOT NULL DEFAULT FALSE,

    feature_build_at                      TIMESTAMPTZ NOT NULL
                                          DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (customer_id, snapshot_date),

    CONSTRAINT chk_vinfast_feature_non_negative_counts
        CHECK (
            order_created_count_daily >= 0
            AND order_created_count_l1m >= 0
            AND order_created_count_l3m >= 0
            AND order_created_count_l12m >= 0
            AND completed_order_count_l1m >= 0
            AND completed_order_count_l3m >= 0
            AND completed_order_count_l12m >= 0
            AND vehicle_order_count_l1m >= 0
            AND vehicle_completed_order_count_l1m >= 0
            AND accessories_order_count_l1m >= 0
            AND work_order_count_l1m >= 0
            AND nvso_order_count_l1m >= 0
            AND discount_order_count_l1m >= 0
        ),

    CONSTRAINT chk_vinfast_feature_date_order
        CHECK (
            first_order_date IS NULL
            OR last_order_date IS NULL
            OR first_order_date <= last_order_date
        )
);

COMMENT ON TABLE feature.vinfast_transaction IS
'VinFast feature table. One row per customer and snapshot date. Sprint 1 supports buyer/order analysis only, not confirmed vehicle ownership.';

CREATE INDEX IF NOT EXISTS idx_vinfast_transaction_snapshot
    ON feature.vinfast_transaction (snapshot_date);

CREATE INDEX IF NOT EXISTS idx_vinfast_transaction_buyer
    ON feature.vinfast_transaction (snapshot_date, is_vinfast_buyer);


-- ----------------------------------------------------------------------------
-- 3. METADATA & ONTOLOGY
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS metadata.feature_catalog (
    feature_id              BIGSERIAL PRIMARY KEY,

    feature_name            VARCHAR(200) NOT NULL UNIQUE,
    table_schema            VARCHAR(100) NOT NULL DEFAULT 'feature',
    table_name              VARCHAR(100) NOT NULL,

    business_unit           VARCHAR(50) NOT NULL,
    feature_group           VARCHAR(100),

    description_vi          TEXT NOT NULL,
    description_en          TEXT,

    data_type               VARCHAR(50) NOT NULL,
    aggregation_type        VARCHAR(50),
    time_window             VARCHAR(30),

    source_schema           VARCHAR(100),
    source_table            VARCHAR(100),
    source_column           VARCHAR(200),
    calculation_expression  TEXT,

    null_meaning            TEXT,
    unit                    VARCHAR(50),

    sensitivity_level       VARCHAR(30) NOT NULL DEFAULT 'internal',
    is_queryable            BOOLEAN NOT NULL DEFAULT TRUE,
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_feature_catalog_bu
        CHECK (business_unit IN ('GSM', 'VINFAST', 'CROSS_BU')),

    CONSTRAINT chk_feature_catalog_sensitivity
        CHECK (
            sensitivity_level IN ('public', 'internal', 'restricted')
        ),

    CONSTRAINT uq_feature_catalog_location
        UNIQUE (table_schema, table_name, feature_name)
);

COMMENT ON TABLE metadata.feature_catalog IS
'Canonical registry for feature retrieval, SQL generation and business explanations.';

CREATE INDEX IF NOT EXISTS idx_feature_catalog_table
    ON metadata.feature_catalog (table_schema, table_name);

CREATE INDEX IF NOT EXISTS idx_feature_catalog_group
    ON metadata.feature_catalog (business_unit, feature_group);

CREATE INDEX IF NOT EXISTS idx_feature_catalog_queryable
    ON metadata.feature_catalog (is_active, is_queryable);


CREATE TABLE IF NOT EXISTS metadata.feature_synonyms (
    synonym_id             BIGSERIAL PRIMARY KEY,
    feature_id             BIGINT NOT NULL
                           REFERENCES metadata.feature_catalog(feature_id)
                           ON DELETE CASCADE,

    synonym_text           VARCHAR(200) NOT NULL,
    language_code          VARCHAR(10) NOT NULL DEFAULT 'vi',
    synonym_type           VARCHAR(30) NOT NULL DEFAULT 'business',

    is_active              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_feature_synonym_type
        CHECK (
            synonym_type IN (
                'business',
                'technical',
                'abbreviation',
                'natural_language'
            )
        ),

    CONSTRAINT uq_feature_synonym
        UNIQUE (feature_id, synonym_text, language_code)
);

CREATE INDEX IF NOT EXISTS idx_feature_synonyms_text
    ON metadata.feature_synonyms (synonym_text);

CREATE INDEX IF NOT EXISTS idx_feature_synonyms_feature
    ON metadata.feature_synonyms (feature_id, is_active);


CREATE TABLE IF NOT EXISTS metadata.business_terms (
    term_id                BIGSERIAL PRIMARY KEY,

    term_text              VARCHAR(200) NOT NULL,
    business_unit          VARCHAR(50),

    definition             TEXT NOT NULL,
    clarification_text     TEXT,

    is_ambiguous           BOOLEAN NOT NULL DEFAULT FALSE,
    is_active              BOOLEAN NOT NULL DEFAULT TRUE,

    created_at             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_business_terms_bu
        CHECK (
            business_unit IS NULL
            OR business_unit IN ('GSM', 'VINFAST', 'GLOBAL')
        ),

    CONSTRAINT uq_business_term
        UNIQUE (term_text, business_unit)
);

COMMENT ON TABLE metadata.business_terms IS
'Business glossary used to clarify ambiguous Vietnamese terms such as VIP, active customer, buyer and owner.';


CREATE TABLE IF NOT EXISTS metadata.term_feature_map (
    term_feature_map_id    BIGSERIAL PRIMARY KEY,

    term_id                BIGINT NOT NULL
                           REFERENCES metadata.business_terms(term_id)
                           ON DELETE CASCADE,

    feature_id             BIGINT NOT NULL
                           REFERENCES metadata.feature_catalog(feature_id)
                           ON DELETE CASCADE,

    relevance_score        NUMERIC(5,4) NOT NULL DEFAULT 1,
    mapping_type           VARCHAR(30) NOT NULL DEFAULT 'direct',

    is_active              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_term_feature_relevance
        CHECK (relevance_score BETWEEN 0 AND 1),

    CONSTRAINT chk_term_feature_mapping_type
        CHECK (
            mapping_type IN (
                'direct',
                'derived',
                'supporting',
                'exclusion'
            )
        ),

    CONSTRAINT uq_term_feature_map
        UNIQUE (term_id, feature_id)
);

CREATE INDEX IF NOT EXISTS idx_term_feature_map_term
    ON metadata.term_feature_map (term_id, is_active);

CREATE INDEX IF NOT EXISTS idx_term_feature_map_feature
    ON metadata.term_feature_map (feature_id, is_active);


-- ----------------------------------------------------------------------------
-- 4. AGENT USERS, QUERY LOGS AND SQL VALIDATION
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS agent.agent_users (
    user_id                BIGSERIAL PRIMARY KEY,

    username               VARCHAR(100) NOT NULL UNIQUE,
    display_name           VARCHAR(200),
    email                  VARCHAR(200) UNIQUE,

    role                   VARCHAR(30) NOT NULL,
    business_unit          VARCHAR(50),

    is_active              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_agent_users_role
        CHECK (
            role IN (
                'business_user',
                'analyst',
                'engineer',
                'admin'
            )
        ),

    CONSTRAINT chk_agent_users_bu
        CHECK (
            business_unit IS NULL
            OR business_unit IN ('GSM', 'VINFAST', 'GLOBAL')
        )
);

CREATE TABLE IF NOT EXISTS agent.query_log (
    query_id                 BIGSERIAL PRIMARY KEY,

    user_id                  BIGINT
                             REFERENCES agent.agent_users(user_id),

    session_id               VARCHAR(100),

    query_text               TEXT NOT NULL,
    normalized_query         TEXT,
    detected_intent          VARCHAR(100),

    selected_business_unit   VARCHAR(50),
    selected_tables          JSONB,
    retrieved_features       JSONB,
    selected_features        JSONB,

    generated_sql            TEXT,
    validated_sql            TEXT,

    execution_status         VARCHAR(30) NOT NULL,
    row_count                BIGINT,
    execution_time_ms        INTEGER,

    confidence_score         NUMERIC(5,4),
    warning_message          TEXT,
    error_message            TEXT,

    result_preview           JSONB,

    created_at               TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_query_log_status
        CHECK (
            execution_status IN (
                'received',
                'retrieved',
                'clarification_required',
                'generated',
                'validated',
                'executed',
                'rejected',
                'failed'
            )
        ),

    CONSTRAINT chk_query_log_confidence
        CHECK (
            confidence_score IS NULL
            OR confidence_score BETWEEN 0 AND 1
        ),

    CONSTRAINT chk_query_log_execution_time
        CHECK (
            execution_time_ms IS NULL
            OR execution_time_ms >= 0
        ),

    CONSTRAINT chk_query_log_row_count
        CHECK (
            row_count IS NULL
            OR row_count >= 0
        )
);

COMMENT ON TABLE agent.query_log IS
'Audit log for the full Text-to-SQL lifecycle: question, retrieval, selected features, SQL, validation, execution and result preview.';

CREATE INDEX IF NOT EXISTS idx_query_log_user_time
    ON agent.query_log (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_query_log_status_time
    ON agent.query_log (execution_status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_query_log_business_unit
    ON agent.query_log (selected_business_unit, created_at DESC);


CREATE TABLE IF NOT EXISTS agent.sql_validation_log (
    validation_id            BIGSERIAL PRIMARY KEY,

    query_id                 BIGINT NOT NULL
                             REFERENCES agent.query_log(query_id)
                             ON DELETE CASCADE,

    validator_version        VARCHAR(50),
    sql_text                 TEXT NOT NULL,

    is_select_only           BOOLEAN NOT NULL DEFAULT FALSE,
    has_select_star          BOOLEAN NOT NULL DEFAULT FALSE,
    accesses_raw_schema      BOOLEAN NOT NULL DEFAULT FALSE,
    accesses_restricted_data BOOLEAN NOT NULL DEFAULT FALSE,
    has_disallowed_statement BOOLEAN NOT NULL DEFAULT FALSE,
    has_row_limit            BOOLEAN NOT NULL DEFAULT FALSE,

    referenced_tables        JSONB,
    referenced_columns       JSONB,
    validation_errors        JSONB,
    validation_warnings      JSONB,

    is_valid                 BOOLEAN NOT NULL,
    validated_at             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE agent.sql_validation_log IS
'Stores SQL validator results. Sprint 1 must enforce SELECT-only access to approved feature and metadata tables.';

CREATE INDEX IF NOT EXISTS idx_sql_validation_query
    ON agent.sql_validation_log (query_id);

CREATE INDEX IF NOT EXISTS idx_sql_validation_validated_at
    ON agent.sql_validation_log (validated_at DESC);


-- ----------------------------------------------------------------------------
-- 5. QUERY ACCURACY / EVALUATION
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS eval.query_test_case (
    test_case_id            BIGSERIAL PRIMARY KEY,

    test_case_code          VARCHAR(100) NOT NULL UNIQUE,
    question_vi             TEXT NOT NULL,

    expected_business_unit  VARCHAR(50),
    expected_tables         JSONB,
    expected_features       JSONB NOT NULL,
    expected_sql            TEXT,
    expected_result         JSONB,

    difficulty_level        VARCHAR(20) NOT NULL DEFAULT 'medium',
    test_category           VARCHAR(50) NOT NULL,

    tolerance_config        JSONB,
    notes                   TEXT,

    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_query_test_case_difficulty
        CHECK (
            difficulty_level IN ('easy', 'medium', 'hard')
        ),

    CONSTRAINT chk_query_test_case_category
        CHECK (
            test_category IN (
                'single_feature',
                'time_comparison',
                'service_breakdown',
                'ambiguous_question',
                'out_of_scope',
                'restricted_data',
                'sql_safety',
                'buyer_vs_owner',
                'cross_bu'
            )
        )
);

COMMENT ON TABLE eval.query_test_case IS
'Golden test set used to measure retrieval accuracy, feature selection accuracy, SQL validity and answer accuracy.';


CREATE TABLE IF NOT EXISTS eval.query_test_run (
    test_run_id                 BIGSERIAL PRIMARY KEY,

    test_case_id                BIGINT NOT NULL
                                REFERENCES eval.query_test_case(test_case_id),

    query_id                    BIGINT
                                REFERENCES agent.query_log(query_id),

    retriever_version           VARCHAR(50),
    prompt_version              VARCHAR(50),
    model_name                  VARCHAR(100),

    actual_tables               JSONB,
    actual_features             JSONB,
    actual_sql                  TEXT,
    actual_result               JSONB,

    retrieval_correct           BOOLEAN,
    feature_selection_correct   BOOLEAN,
    sql_valid                   BOOLEAN,
    result_correct              BOOLEAN,

    retrieval_score             NUMERIC(5,4),
    feature_selection_score     NUMERIC(5,4),
    result_score                NUMERIC(5,4),

    failure_reason              TEXT,
    executed_at                 TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_test_run_retrieval_score
        CHECK (
            retrieval_score IS NULL
            OR retrieval_score BETWEEN 0 AND 1
        ),

    CONSTRAINT chk_test_run_feature_score
        CHECK (
            feature_selection_score IS NULL
            OR feature_selection_score BETWEEN 0 AND 1
        ),

    CONSTRAINT chk_test_run_result_score
        CHECK (
            result_score IS NULL
            OR result_score BETWEEN 0 AND 1
        )
);

CREATE INDEX IF NOT EXISTS idx_query_test_run_case
    ON eval.query_test_run (test_case_id, executed_at DESC);

CREATE INDEX IF NOT EXISTS idx_query_test_run_executed_at
    ON eval.query_test_run (executed_at DESC);


-- ----------------------------------------------------------------------------
-- 6. AGENT-READABLE METADATA VIEW
-- ----------------------------------------------------------------------------

CREATE OR REPLACE VIEW metadata.queryable_feature_view AS
SELECT
    fc.feature_id,
    fc.feature_name,
    fc.table_schema,
    fc.table_name,
    fc.business_unit,
    fc.feature_group,
    fc.description_vi,
    fc.data_type,
    fc.aggregation_type,
    fc.time_window,
    fc.unit,
    fc.null_meaning,
    COALESCE(
        jsonb_agg(
            DISTINCT jsonb_build_object(
                'text', fs.synonym_text,
                'language', fs.language_code,
                'type', fs.synonym_type
            )
        ) FILTER (WHERE fs.synonym_id IS NOT NULL),
        '[]'::jsonb
    ) AS synonyms
FROM metadata.feature_catalog fc
LEFT JOIN metadata.feature_synonyms fs
    ON fs.feature_id = fc.feature_id
   AND fs.is_active = TRUE
WHERE fc.is_active = TRUE
  AND fc.is_queryable = TRUE
  AND fc.sensitivity_level <> 'restricted'
GROUP BY
    fc.feature_id,
    fc.feature_name,
    fc.table_schema,
    fc.table_name,
    fc.business_unit,
    fc.feature_group,
    fc.description_vi,
    fc.data_type,
    fc.aggregation_type,
    fc.time_window,
    fc.unit,
    fc.null_meaning;

COMMENT ON VIEW metadata.queryable_feature_view IS
'Flattened retrieval view containing queryable features and their synonyms.';


-- ----------------------------------------------------------------------------
-- 7. OPTIONAL SECURITY ROLES
-- Run this section with a privileged database account.
-- The DO blocks are idempotent.
-- ----------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'feature_agent_reader'
    ) THEN
        CREATE ROLE feature_agent_reader NOLOGIN;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'feature_agent_logger'
    ) THEN
        CREATE ROLE feature_agent_logger NOLOGIN;
    END IF;
END
$$;

-- Read-only access for the agent.
GRANT USAGE ON SCHEMA feature, metadata TO feature_agent_reader;

GRANT SELECT ON
    feature.gsm_transaction,
    feature.vinfast_transaction,
    metadata.feature_catalog,
    metadata.feature_synonyms,
    metadata.business_terms,
    metadata.term_feature_map,
    metadata.queryable_feature_view
TO feature_agent_reader;

-- Explicitly deny raw-data access.
REVOKE ALL ON SCHEMA raw FROM feature_agent_reader;
REVOKE ALL ON ALL TABLES IN SCHEMA raw FROM feature_agent_reader;

-- Logging role.
GRANT USAGE ON SCHEMA agent TO feature_agent_logger;

GRANT INSERT, SELECT ON
    agent.query_log,
    agent.sql_validation_log
TO feature_agent_logger;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA agent
TO feature_agent_logger;


-- ----------------------------------------------------------------------------
-- 8. DEFAULT PRIVILEGES
-- These statements affect future objects created by the current migration owner.
-- ----------------------------------------------------------------------------

ALTER DEFAULT PRIVILEGES IN SCHEMA feature
    GRANT SELECT ON TABLES TO feature_agent_reader;

ALTER DEFAULT PRIVILEGES IN SCHEMA metadata
    GRANT SELECT ON TABLES TO feature_agent_reader;

ALTER DEFAULT PRIVILEGES IN SCHEMA raw
    REVOKE ALL ON TABLES FROM feature_agent_reader;


COMMIT;

-- ============================================================================
-- END OF SPRINT 1 SCHEMA
-- ============================================================================
