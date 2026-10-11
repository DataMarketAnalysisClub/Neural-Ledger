"""Adapter for providers that speak the OpenAI chat-completions format with tool calling.

OpenRouter is a thin subclass that only sets the provider name, base URL, key variable and any
provider-specific request fields; another compatible provider would be one more such subclass. Standard library only (urllib), so the core stays
dependency-free. Endpoint: POST {base_url}/chat/completions with a Bearer key. Tool calls come back
as `message.tool_calls[].function.arguments`, a JSON *string*; tool results go back as `role: tool`
messages. Any network, HTTP or malformed-response error raises LanguageModelUnavailable, so
FallbackLanguageModel can switch to the scripted model.

Security notes:
- Arguments that are not a JSON object become `{}`; the tool's strict input validation then
  returns INVALID_INPUT. Model output never reaches an engine unvalidated.
- The API key only travels in the Authorization header and is never put in an error message.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Mapping
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

logger = logging.getLogger(__name__)

# Some providers sit behind a CDN that rejects urllib's default User-Agent, so send our own.
USER_AGENT = "neural-ledger/0.1"


class OpenAICompatibleLanguageModel:
    provider = "openai-compatible"
    key_variable = "API_KEY"
    default_base_url = ""
    extra_body: Mapping[str, Any] = {}  # provider-specific request fields

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str | None = None,
        max_tokens: int = 2048,
        temperature: float | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError(f"{self.key_variable} is required for the {self.provider} adapter")
        self.name = f"{self.provider}:{model}"
        self._api_key = api_key
        self._model = model
        self._url = (base_url or self.default_base_url).rstrip("/") + "/chat/completions"
        self._max_tokens = max_tokens
        self._temperature = temperature  # None = not sent: some models (Claude 5.x) reject it
        self._timeout_s = timeout_s

    def respond(self, request: ModelRequest) -> ModelTurn:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "system", "content": request.system}, *_messages(request)],
            "max_tokens": self._max_tokens,
            **self.extra_body,
        }
        if self._temperature is not None:
            body["temperature"] = self._temperature
        if request.tools:
            body["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": dict(t.input_schema)}}
                for t in request.tools
            ]
        http_request = urllib.request.Request(
            self._url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=self._timeout_s) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise LanguageModelUnavailable(f"{self.provider} returned HTTP {exc.code}: {_error_detail(exc)}") from exc
        except (OSError, json.JSONDecodeError) as exc:  # URLError and timeouts are OSError
            raise LanguageModelUnavailable(f"{self.provider} request failed: {exc}") from exc
        if isinstance(data, dict) and data.get("error"):  # some providers report generation errors with HTTP 200
            raise LanguageModelUnavailable(f"{self.provider} returned an error: {str(data['error'])[:300]}")
        try:
            choice = data["choices"][0]
            message = choice["message"]
            calls = tuple(_tool_call(raw) for raw in message.get("tool_calls") or [])
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise LanguageModelUnavailable(f"{self.provider} returned an unexpected response: {exc!r}") from exc
        text = (message.get("content") or "").strip() or None
        if not text and not calls:
            # Typically finish_reason=length: a reasoning model spent the whole output budget thinking.
            logger.warning("%s returned an empty reply (finish_reason=%s)", self.name, choice.get("finish_reason"))
        return ModelTurn(text if not calls else None, calls, self.name)


def _error_detail(exc: urllib.error.HTTPError) -> str:
    """The provider's error body (truncated), so a silent fallback can be diagnosed. It never contains the request key."""
    try:
        return exc.read(500).decode("utf-8", errors="replace").strip() or str(exc.reason)
    except OSError:
        return str(exc.reason)


def _tool_call(raw: dict[str, Any]) -> ToolCall:
    function = raw["function"]
    return ToolCall(str(raw["id"]), str(function["name"]), _arguments(function.get("arguments")))


def _arguments(raw: Any) -> dict[str, Any]:
    """The provider sends a JSON string. Anything that is not a JSON object becomes {} (fail closed)."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _messages(request: ModelRequest) -> list[dict[str, Any]]:
    """Map entries to chat messages. History trimming can cut a tool exchange in half, so start at a user message."""
    messages: list[dict[str, Any]] = []
    for entry in request.entries:
        if isinstance(entry, UserEntry):
            messages.append({"role": "user", "content": entry.text})
        elif isinstance(entry, AssistantEntry):
            message: dict[str, Any] = {"role": "assistant", "content": entry.text or None}
            if entry.tool_calls:
                message["tool_calls"] = [
                    {"id": c.call_id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(dict(c.arguments))}}
                    for c in entry.tool_calls
                ]
            if entry.text or entry.tool_calls:
                messages.append(message)
        elif isinstance(entry, ToolResultEntry):
            messages.append({"role": "tool", "tool_call_id": entry.call_id, "content": json.dumps(entry.payload)})
    while messages and messages[0]["role"] != "user":
        messages.pop(0)
    return messages
