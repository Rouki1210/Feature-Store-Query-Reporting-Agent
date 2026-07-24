"""Cấu hình ứng dụng — nạp từ biến môi trường / `.env` (config-only).

Nguyên tắc CLAUDE.md mục 5: không hardcode credential, threshold hay DB URL.
Mọi hằng số vận hành đều đi qua đây.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- LLM (OpenAI-compatible: key + model + base_url) ----
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_base_url: str = Field(default="https://api.openai.com/v1", alias="LLM_BASE_URL")
    llm_model: str = Field(default="gpt-4o", alias="LLM_MODEL")
    llm_model_narrator: str = Field(default="", alias="LLM_MODEL_NARRATOR")

    # ---- Database (Postgres target) ----
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/feature_store",
        alias="DATABASE_URL",
    )

    # ---- SQL guards ----
    sql_max_rows: int = Field(default=1000, alias="SQL_MAX_ROWS")
    sql_sensitive_columns: str = Field(
        default="customer_name,phone,phone_number,email,national_id,cccd,address,dob,full_name",
        alias="SQL_SENSITIVE_COLUMNS",
    )
    sql_max_repairs: int = Field(default=2, alias="SQL_MAX_REPAIRS")
    llm_timeout_seconds: float = Field(default=30.0, alias="LLM_TIMEOUT_SECONDS")
    llm_network_retries: int = Field(default=1, alias="LLM_NETWORK_RETRIES")
    agent_max_question_chars: int = Field(default=2000, alias="AGENT_MAX_QUESTION_CHARS")

    # ---- Retrieval ----
    retrieval_top_k: int = Field(default=8, alias="RETRIEVAL_TOP_K")
    # Điểm top tối thiểu để coi là "khớp đủ tin cậy". Dưới ngưỡng ⇒ câu hỏi quá
    # mơ hồ ⇒ hỏi lại (mục 5), không sinh SQL "gọi tất cả". Calib: câu cụ thể ≥2.75,
    # mơ hồ ≤1.5.
    retrieval_min_score: float = Field(default=2.0, alias="RETRIEVAL_MIN_SCORE")

    # ---- Conversation (multi-turn clarify) ----
    # TTL của pending question (short-term state). Hết hạn ⇒ coi câu trả lời ngắn
    # là câu hỏi mới. Spec đề xuất 10–15 phút.
    conversation_ttl_seconds: int = Field(default=900, alias="CONVERSATION_TTL_SECONDS")

    # ---- App ----
    semantic_layer_path: str = Field(
        default="./data/semantic_layer.yaml", alias="SEMANTIC_LAYER_PATH"
    )
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173", alias="CORS_ORIGINS"
    )

    @property
    def sensitive_columns(self) -> list[str]:
        return [c.strip().lower() for c in self.sql_sensitive_columns.split(",") if c.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def narrator_model(self) -> str:
        return self.llm_model_narrator or self.llm_model


@lru_cache
def get_settings() -> Settings:
    return Settings()
