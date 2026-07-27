from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models.schemas import QueryResult


class IntentType(str, Enum):
    single_bu = "single_bu"
    aggregate = "aggregate"
    filter = "filter"
    window_compare = "window_compare"
    clarify = "clarify"
    out_of_scope = "out_of_scope"


class RefusalCode(str, Enum):
    cross_pnl = "cross_pnl"
    vehicle_owner = "vehicle_owner"
    raw_or_pii = "raw_or_pii"
    out_of_catalog = "out_of_catalog"
    needs_review = "needs_review"
    irrelevant = "irrelevant" 


class RouteDecision(BaseModel):
    intent: IntentType
    business_unit: str | None = None
    confidence: float = Field(ge=0, le=1)
    reason: str = ""
    refusal_code: RefusalCode | None = None
    clarifying_question: str | None = None


class GenerationRequest(BaseModel):
    question: str
    route: RouteDecision
    feature_context: str


class GenerationResponse(BaseModel):
    sql: str
    selected_features: list[str] = Field(default_factory=list)
    intent: IntentType
    assumptions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)

    @field_validator("selected_features", "assumptions", mode="before")
    @classmethod
    def coerce_string_lists(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return value


class ValidationResult(BaseModel):
    valid: bool
    sql: str | None = None
    errors: list[str] = Field(default_factory=list)
    referenced_tables: list[str] = Field(default_factory=list)
    selected_features: list[str] = Field(default_factory=list)


class PipelineContext(BaseModel):
    original_question: str
    normalized_question: str
    route: RouteDecision
    retrieved: list[dict[str, Any]] = Field(default_factory=list)
    generation: GenerationResponse | None = None
    validation: ValidationResult | None = None
    repairs: int = 0


class RepairRequest(BaseModel):
    question: str
    previous_sql: str
    error: str
    feature_context: str


class NarrationInput(BaseModel):
    question: str
    sql: str
    result: QueryResult
    confidence: float
    coverage_note: str | None = None
