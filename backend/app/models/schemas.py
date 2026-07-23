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


class RetrievedFeature(BaseModel):
    name: str
    table: str
    group: str
    description_vi: str
    description_en: str = ""
    score: float


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
    answer_vi: str = Field(default="", description="Diễn giải ngắn bằng tiếng Việt")
    sql: str | None = Field(default=None, description="SQL đã sinh — luôn hiển thị để kiểm chứng")
    result: QueryResult | None = None
    retrieved: list[RetrievedFeature] = Field(default_factory=list)
    confidence: Confidence = Confidence.medium
    coverage: CoverageInfo | None = None
    repairs: int = Field(default=0, description="Số lần tự sửa SQL đã dùng")
    clarifying_question: str | None = None
    error: str | None = None


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
