"""Anthropic Messages API adapter (reference implementation; the provider is decision D-02).

Standard library only (urllib), so the core stays dependency-free. OpenAI or Gemini adapters
implement the same LanguageModel port. Any network or API error raises
LanguageModelUnavailable, so FallbackLanguageModel can switch to the scripted model.
Untested without a key: verify against https://docs.claude.com before relying on it.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from ....application.conversation import (
    AssistantEntry,
    ModelRequest,
    ModelTurn,
    ToolCall,
    ToolResultEntry,
    UserEntry,
)
from ....application.ports import LanguageModelUnavailable

API_VERSION = "2023-06-01"


class AnthropicLanguageModel:
    def __init__(self, api_key: str, model: str, *, base_url: str = "https://api.anthropic.com", max_tokens: int = 1024, timeout_s: float = 30.0) -> None:
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for the anthropic adapter")
        self.name = f"anthropic:{model}"
        self._api_key = api_key
        self._model = model
        self._url = base_url.rstrip("/") + "/v1/messages"
        self._max_tokens = max_tokens
        self._timeout_s = timeout_s

    def respond(self, request: ModelRequest) -> ModelTurn:
        body = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": request.system,
            "messages": _messages(request),
            "tools": [{"name": t.name, "description": t.description, "input_schema": dict(t.input_schema)} for t in request.tools],
        }
        if not body["tools"]:
            del body["tools"]
        http_request = urllib.request.Request(
            self._url,
            data=json.dumps(body).encode("utf-8"),
            headers={"x-api-key": self._api_key, "anthropic-version": API_VERSION, "content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=self._timeout_s) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LanguageModelUnavailable(f"anthropic request failed: {exc}") from exc
        texts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        calls = tuple(
            ToolCall(b["id"], b["name"], b.get("input") or {}) for b in data.get("content", []) if b.get("type") == "tool_use"
        )
        text = "\n".join(t for t in texts if t).strip() or None
        return ModelTurn(text if not calls else None, calls, self.name)


def _messages(request: ModelRequest) -> list[dict[str, Any]]:
    """Map entries to alternating user/assistant messages; tool results travel in user messages."""
    messages: list[dict[str, Any]] = []

    def push(role: str, blocks: list[dict[str, Any]]) -> None:
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"].extend(blocks)
        else:
            messages.append({"role": role, "content": blocks})

    for entry in request.entries:
        if isinstance(entry, UserEntry):
            push("user", [{"type": "text", "text": entry.text}])
        elif isinstance(entry, AssistantEntry):
            blocks: list[dict[str, Any]] = []
            if entry.text:
                blocks.append({"type": "text", "text": entry.text})
            blocks += [{"type": "tool_use", "id": c.call_id, "name": c.name, "input": dict(c.arguments)} for c in entry.tool_calls]
            if blocks:
                push("assistant", blocks)
        elif isinstance(entry, ToolResultEntry):
            push(
                "user",
                [{"type": "tool_result", "tool_use_id": entry.call_id, "content": json.dumps(entry.payload), "is_error": entry.is_error}],
            )
    # history trimming can cut a tool exchange in half: start at a plain user message
    while messages and (messages[0]["role"] != "user" or any(b["type"] == "tool_result" for b in messages[0]["content"])):
        messages.pop(0)
    return messages
