"""Quick Streamlit UI for manually testing the AgentPipeline.

Run from backend/:
    streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

# Streamlit executes this file with backend/app on sys.path. Add backend so
# imports such as `app.agent...` resolve consistently from any launch folder.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import streamlit as st

from app.agent.conversation import ask_with_context
from app.agent.generator import SQLGenerator, SYSTEM_PROMPT
from app.agent.llm_client import OpenAIJSONClient
from app.agent.pipeline import AgentPipeline
from app.config import get_settings


st.set_page_config(
    page_title="Sprint 1 Feature Agent",
    page_icon="🔎",
    layout="wide",
)


@st.cache_resource
def get_pipeline() -> AgentPipeline:
    return AgentPipeline(SQLGenerator(OpenAIJSONClient(get_settings())))


def _render_response(response) -> None:
    status = response.status
    if status == "ok":
        st.success("Query hoàn tất")
    elif status == "clarify":
        st.warning("Cần làm rõ câu hỏi")
    elif status == "out_of_scope":
        st.info("Câu hỏi ngoài phạm vi Sprint 1")
    else:
        st.error("Pipeline trả về lỗi")

    if response.answer_vi:
        st.markdown("### Trả lời")
        st.write(response.answer_vi)
    if response.clarifying_question:
        st.info(response.clarifying_question)
    if response.error:
        st.code(response.error)

    left, right = st.columns(2)
    with left:
        st.metric("Confidence", response.confidence.value)
    with right:
        st.metric("Repairs", response.repairs)

    if response.coverage:
        ratio = response.coverage.non_null_ratio
        st.caption(
            f"Coverage: {ratio:.1%}" if ratio is not None else "Coverage: chưa tính được"
        )
        if response.coverage.note:
            st.caption(response.coverage.note)

    if response.sql:
        st.markdown("### SQL đã validate")
        st.code(response.sql, language="sql")

    if response.pipeline_trace:
        st.markdown("### Pipeline trace")
        st.caption("Hiển thị stage, component được gọi và output rút gọn của từng bước.")
        st.dataframe(
            [
                {
                    "stage": item.get("stage"),
                    "component": item.get("component"),
                    "status": item.get("status"),
                }
                for item in response.pipeline_trace
            ],
            use_container_width=True,
            hide_index=True,
        )
        for index, item in enumerate(response.pipeline_trace, start=1):
            label = f"{index}. {item.get('stage')} — {item.get('component')} [{item.get('status')}]"
            with st.expander(label):
                st.markdown("**Input**")
                st.json(item.get("input"))
                st.markdown("**Output**")
                st.json(item.get("output"))

    with st.expander("Raw AskResponse JSON"):
        st.code(
            json.dumps(response.model_dump(mode="json"), ensure_ascii=False, indent=2),
            language="json",
        )

    if response.retrieved:
        st.markdown("### Features được retrieve")
        st.dataframe(
            [
                {
                    "name": f.name,
                    "table": f.table,
                    "group": f.group,
                    "score": f.score,
                    "description_vi": f.description_vi,
                }
                for f in response.retrieved
            ],
            use_container_width=True,
            hide_index=True,
        )

    if response.result:
        st.markdown("### Kết quả")
        st.caption(
            f"{response.result.row_count} dòng"
            + (" — đã áp row limit" if response.result.truncated else "")
        )
        st.dataframe(
            [
                dict(zip(response.result.columns, row))
                for row in response.result.rows
            ],
            use_container_width=True,
            hide_index=True,
        )


def main() -> None:
    settings = get_settings()
    if "session_id" not in st.session_state:
        st.session_state.session_id = uuid.uuid4().hex[:12]
    if "history" not in st.session_state:
        st.session_state.history = []

    st.title("🔎 Sprint 1 Feature Agent")
    st.caption("Giao diện thử nhanh cho pipeline GSM/VinFast — chỉ truy vấn feature/metadata.")

    with st.sidebar:
        st.subheader("Runtime")
        st.write(f"Model: `{settings.llm_model}`")
        st.write(f"Database: `{settings.database_url.split('@')[-1]}`")
        st.write(f"Session: `{st.session_state.session_id}`")
        if not settings.llm_api_key:
            st.warning("LLM_API_KEY chưa được cấu hình.")
        if st.button("Xóa lịch sử"):
            st.session_state.history = []
            st.rerun()
        if st.button("Reload pipeline"):
            get_pipeline.clear()
            st.session_state.history = []
            st.rerun()
        st.markdown("**Ví dụ**")
        st.caption("• GSM có bao nhiêu chuyến trong tháng gần nhất?")
        st.caption("• Tổng tiền đơn VinFast l1m?")
        st.caption("• Khách nào là chủ sở hữu xe? (sẽ bị từ chối)")
        with st.expander("SQL Generator system prompt"):
            st.code(SYSTEM_PROMPT, language="text")

    for item in st.session_state.history:
        with st.chat_message("user"):
            st.write(item["question"])
        with st.chat_message("assistant"):
            _render_response(item["response"])

    question = st.chat_input("Nhập câu hỏi bằng tiếng Việt…")
    if question:
        with st.chat_message("user"):
            st.write(question)
        with st.chat_message("assistant"):
            with st.spinner("Đang route, generate, validate và execute…"):
                try:
                    response = ask_with_context(
                        get_pipeline(), st.session_state.session_id, question
                    )
                    _render_response(response)
                except Exception as exc:
                    st.error(f"Không thể chạy pipeline: {exc}")
                    response = None
        if response is not None:
            st.session_state.history.append({"question": question, "response": response})


if __name__ == "__main__":
    main()
