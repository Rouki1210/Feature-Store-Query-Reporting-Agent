"""FastAPI app — REST mỏng bọc AgentPipeline (mục 6 bước 7).

Chạy (từ backend/):  uvicorn app.main:app --reload
Pipeline build lazy (@lru_cache) nên import module này KHÔNG chạm DB/LLM.
"""
from __future__ import annotations

import uuid
from functools import lru_cache

from fastapi import FastAPI, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.agent.conversation import ask_with_context
from app.agent.breakdown import BreakdownPlanner
from app.agent.generator import SQLGenerator
from app.agent.llm_client import OpenAIJSONClient
from app.agent.pipeline import AgentPipeline
from app.config import get_settings
from app.db import dialect_name, get_engine
from app.models.schemas import AskRequest, AskResponse, FeatureSummary, HealthResponse
from app.semantic.retriever import get_semantic_layer

app = FastAPI(title="Feature Store Query Agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


@lru_cache
def _pipeline() -> AgentPipeline:
    # Build một lần; __init__ đọc semantic layer từ DB (đã cache riêng).
    try:
        breakdown_planner = BreakdownPlanner.load_from_db()
    except Exception:
        # Migration 0013 có thể chưa được apply ở môi trường vừa deploy; registry
        # canonical vẫn cho agent chạy, còn DB trở lại nguồn runtime sau migration.
        breakdown_planner = BreakdownPlanner()
    return AgentPipeline(
        SQLGenerator(OpenAIJSONClient(get_settings())),
        breakdown_planner=breakdown_planner,
    )


@app.get("/health", response_model=HealthResponse)
def health(response: Response) -> HealthResponse:
    # Query catalog TRỰC TIẾP (không qua get_semantic_layer đã cache) để phản ánh
    # trạng thái DB thật: catalog rỗng ⇒ agent thấy 0 feature ⇒ 503 degraded.
    settings = get_settings()
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
            features = conn.execute(
                text("SELECT count(*) FROM metadata.feature_catalog WHERE is_queryable")
            ).scalar_one()
        dialect = dialect_name()
        status = "ok" if features else "degraded"
    except Exception:
        dialect, features, status = "unavailable", 0, "db_unavailable"
    if status != "ok":
        response.status_code = 503
    return HealthResponse(
        status=status, dialect=dialect, features_loaded=features,
        llm_configured=bool(settings.llm_api_key),
    )


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    # Client gửi lại session_id để tiếp nối câu hỏi đang chờ làm rõ (multi-turn).
    # Lượt đầu bỏ trống → sinh mới; response luôn trả session_id để dùng cho lượt sau.
    session_id = req.session_id or f"api-{uuid.uuid4().hex[:12]}"
    return ask_with_context(_pipeline(), session_id, req.question)


@app.get("/features", response_model=list[FeatureSummary])
def features(
    q: str | None = Query(default=None, description="Nếu có: trả feature khớp câu hỏi; nếu không: liệt kê toàn bộ queryable"),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[FeatureSummary]:
    layer = get_semantic_layer()
    if q:
        hits = layer.retrieve(q, top_k=limit)
        return [
            FeatureSummary(
                name=h.name, table=h.table, group=h.group,
                description_vi=h.description_vi, description_en=h.description_en,
                keywords=h.keywords,
            )
            for h in hits
        ]
    return [
        FeatureSummary(
            name=f["name"], table=f["table"], group=f.get("group", ""),
            description_vi=f.get("description_vi", ""),
            description_en=f.get("description_en", ""),
            keywords=f.get("keywords", []),
        )
        for f in layer.features[:limit]
    ]
