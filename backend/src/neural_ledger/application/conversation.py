"""Provider-neutral conversation types used by the LanguageModel port.

Adapters translate these to each provider's format (Anthropic, OpenAI, Gemini, scripted).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class UserEntry:
    text: str


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AssistantEntry:
    text: str | None
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolResultEntry:
    call_id: str
    name: str
    payload: Mapping[str, Any]  # JSON-safe envelope or block notice
    is_error: bool = False


Entry = UserEntry | AssistantEntry | ToolResultEntry


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    tier: str


@dataclass(frozen=True, slots=True)
class TurnContext:
    """What the application already decided about this turn. Real LLMs get it as context."""

    intent: str
    intent_confidence: float
    gate: str
    max_tier: str
    as_of: str
    currency: str


@dataclass(frozen=True, slots=True)
class ModelRequest:
    system: str
    entries: tuple[Entry, ...]
    tools: tuple[ToolSpec, ...]
    context: TurnContext


@dataclass(frozen=True, slots=True)
class ModelTurn:
    text: str | None
    tool_calls: tuple[ToolCall, ...]
    model_version: str


def entries_since_last_user(entries: tuple[Entry, ...]) -> tuple[Entry, ...]:
    for index in range(len(entries) - 1, -1, -1):
        if isinstance(entries[index], UserEntry):
            return entries[index + 1 :]
    return entries


def last_user_text(entries: tuple[Entry, ...]) -> str:
    for entry in reversed(entries):
        if isinstance(entry, UserEntry):
            return entry.text
    return ""
