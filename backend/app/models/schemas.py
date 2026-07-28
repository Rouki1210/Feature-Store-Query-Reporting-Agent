"""Pydantic schemas cho request/response API."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Confidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class AskRequest(BaseModel):
    question: str = Field(..., description="Câu hỏi nghiệp vụ bằng tiếng Việt")
    session_id: str | None = Field(
        default=None,
        description="Gửi lại session_id nhận ở lượt trước để tiếp nối câu hỏi đang chờ làm rõ.",
    )


class RetrievedFeature(BaseModel):
    name: str
    table: str
    group: str
    description_vi: str
    description_en: str = ""
    score: float
    support_status: str = "queryable"
    dtype: str | None = None
    unit: str | None = None
    null_meaning: str | None = None


class QueryResult(BaseModel):
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False


class CoverageInfo(BaseModel):
    """Độ phủ dữ liệu — bắt buộc gắn cờ khi feature thưa (CLAUDE.md mục 5)."""

    non_null_ratio: float | None = None
    note: str | None = None


class AskResponse(BaseModel):
    # Khi agent không chắc → trả câu hỏi lại thay vì đoán bừa.
    status: str = Field(default="ok", description="ok | clarify | out_of_scope | error")
    session_id: str | None = Field(
        default=None, description="Khóa phiên để client gửi lại ở lượt trả lời tiếp theo."
    )
    answer_vi: str = Field(default="", description="Diễn giải ngắn bằng tiếng Việt")
    sql: str | None = Field(default=None, description="SQL đã sinh — luôn hiển thị để kiểm chứng")
    result: QueryResult | None = None
    retrieved: list[RetrievedFeature] = Field(default_factory=list)
    confidence: Confidence = Confidence.medium
    coverage: CoverageInfo | None = None
    repairs: int = Field(default=0, description="Số lần tự sửa SQL đã dùng")
    clarifying_question: str | None = None
    join_explanation: str | None = None
    known_slots: dict[str, str | int] = Field(default_factory=dict)
    missing_slots: list[str] = Field(default_factory=list)
    refusal_code: str | None = Field(
        default=None, description="Mã từ chối khi out_of_scope/clarify (cho eval guardrail)."
    )
    error: str | None = None
    pipeline_trace: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Trace các stage đã chạy: router, retriever, generator, validator, executor, narrator.",
    )


class FeatureSummary(BaseModel):
    name: str
    table: str
    group: str
    description_vi: str
    description_en: str = ""
    keywords: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    dialect: str
    features_loaded: int
    llm_configured: bool
