from __future__ import annotations

import json
from typing import Any, Protocol

from app.config import Settings, get_settings


class LLMError(RuntimeError):
    pass


def parse_json_object(content: Any) -> dict[str, Any]:
    """Parse common OpenAI-compatible JSON variants without accepting non-objects."""
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        raise LLMError("LLM response content không phải string hoặc object.")
    body = content.strip()
    if body.startswith("```"):
        body = body.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    start = body.find("{")
    if start < 0:
        raise LLMError("LLM response không chứa JSON object.")
    try:
        value, _ = json.JSONDecoder().raw_decode(body[start:])
    except json.JSONDecodeError as exc:
        raise LLMError(
            f"LLM trả JSON không hợp lệ tại vị trí {exc.pos}: {exc.msg}."
        ) from exc
    if not isinstance(value, dict):
        raise LLMError("LLM JSON phải là object.")
    return value


class JSONLLM(Protocol):
    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        ...


class OpenAIJSONClient:
    """Small OpenAI-compatible adapter; never logs credentials or prompts."""

    def __init__(self, settings: Settings | None = None, model: str | None = None):
        self.settings = settings or get_settings()
        self.model = model or self.settings.llm_model
        self._client = None

    def _get_client(self):
        if not self.settings.llm_api_key:
            raise LLMError("LLM_API_KEY chưa được cấu hình.")
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise LLMError("Chưa cài package openai.") from exc
            self._client = OpenAI(
                api_key=self.settings.llm_api_key,
                base_url=self.settings.llm_base_url,
                timeout=self.settings.llm_timeout_seconds,
                max_retries=self.settings.llm_network_retries,
            )
        return self._client

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        client = self._get_client()
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            response = client.chat.completions.create(
                model=self.model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=messages,
            )
        except Exception as exc:
            message = str(exc).lower()
            compatible_error = any(
                marker in message
                for marker in ("json parse", "json mode", "response_format", "unsupported")
            )
            if not compatible_error:
                raise LLMError(f"LLM request failed: {exc}") from exc
            response = client.chat.completions.create(
                model=self.model,
                temperature=0,
                messages=messages,
            )
        content = response.choices[0].message.content or ""
        try:
            return parse_json_object(content)
        except LLMError:
            # One format-repair request for providers that ignore JSON mode.
            repair_messages = messages + [
                {"role": "assistant", "content": content[:4000]},
                {"role": "user", "content": "Return the same answer as exactly one valid JSON object. No Markdown or extra text."},
            ]
            repaired = client.chat.completions.create(
                model=self.model,
                temperature=0,
                messages=repair_messages,
            )
            return parse_json_object(repaired.choices[0].message.content or "")


class StaticJSONClient:
    """Offline test client returning a deterministic payload or callback result."""

    def __init__(self, payload: dict[str, Any] | None = None, callback=None):
        self.payload = payload
        self.callback = callback
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        self.calls.append((system, user))
        if self.callback:
            return self.callback(system, user)
        if self.payload is None:
            raise LLMError("StaticJSONClient chưa có payload.")
        return dict(self.payload)
