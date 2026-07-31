// Mirror backend/app/models/schemas.py — giữ đồng bộ khi schema đổi.

export type Confidence = "high" | "medium" | "low";
export type AskStatus = "ok" | "clarify" | "out_of_scope" | "error";

export interface QueryResult {
  columns: string[];
  rows: unknown[][]; // list-of-list: rows[i][j] ↔ columns[j]
  row_count: number;
  truncated: boolean;
}

export interface RetrievedFeature {
  name: string;
  table: string;
  group: string;
  description_vi: string;
  description_en: string;
  score: number;
  support_status: string;
  dtype: string | null;
  unit: string | null;
  null_meaning: string | null;
}

export interface CoverageInfo {
  non_null_ratio: number | null; // 0..1
  note: string | null;
  is_low: boolean; // backend quyết định theo COVERAGE_LOW_RATIO — đừng giữ ngưỡng riêng ở đây
}

/** Backend quyết định cách hiển thị; frontend không tự đoán từ shape của result. */
export type ResultShape = "scalar" | "time_series" | "category" | "table";

export interface TraceItem {
  stage: string;
  component: string;
  status: string;
  input: unknown;
  output: unknown;
}

export interface AskResponse {
  status: AskStatus;
  session_id: string | null;
  answer_vi: string;
  sql: string | null;
  result: QueryResult | null;
  result_shape: ResultShape;
  assumptions: string[];
  retrieved: RetrievedFeature[];
  confidence: Confidence;
  coverage: CoverageInfo | null;
  repairs: number;
  join_explanation: string | null;
  refusal_code: string | null;
  known_slots: Record<string, string | number>;
  missing_slots: string[];
  clarification_options: { value: string; label: string }[];
  clarifying_question: string | null;
  error: string | null;
  pipeline_trace: TraceItem[];
}

export interface FeatureSummary {
  name: string;
  table: string;
  group: string;
  description_vi: string;
  description_en: string;
  keywords: string[];
}

export interface HealthResponse {
  status: string;
  dialect: string;
  features_loaded: number;
  llm_configured: boolean;
}
