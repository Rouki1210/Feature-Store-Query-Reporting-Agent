from __future__ import annotations

from app.agent.contracts import NarrationInput
from app.agent.llm_client import JSONLLM


def deterministic_answer(inp: NarrationInput) -> str:
    if inp.result.row_count == 0:
        answer = "Không có dữ liệu phù hợp với điều kiện truy vấn."
    else:
        answer = f"Đã tìm thấy {inp.result.row_count} dòng dữ liệu."
        if inp.result.columns:
            answer += f" Các cột kết quả: {', '.join(inp.result.columns)}."
    if inp.result.truncated:
        answer += " Kết quả đã bị giới hạn theo row limit."
    if inp.coverage_note:
        answer += f" Lưu ý: {inp.coverage_note}"
    return answer


class OptionalLLMNarrator:
    """Narrates only validated result data; callers must retain deterministic fallback."""

    def __init__(self, client: JSONLLM):
        self.client = client

    def __call__(self, inp: NarrationInput) -> str:
        payload = self.client.complete_json(
            "You narrate validated analytics results in concise Vietnamese. "
            "Return JSON only: {\"answer_vi\": \"...\"}. Never invent values or claim ownership.",
            inp.model_dump_json(ensure_ascii=False),
        )
        answer = payload.get("answer_vi")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("Narrator không trả answer_vi hợp lệ.")
        return answer.strip()
