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
    # The id of a message the user sent, given before any tool runs: a memory origin points at it (ADR-048 §3).
    # None for text the application writes in the user's turn (a repair note). Adapters never send it to a model.
    message_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)


# (consent_generation, memory_revision) of the user's memory when a turn read it (ADR-048 §6). A turn that called a
# memory tool, or that saw such a turn in its history, stamps its assistant and tool entries; once either counter
# moves, those entries are stale and never reach a model again. Adapters never send the stamp to a model.
MemoryStamp = tuple[int, int]


@dataclass(frozen=True, slots=True)
class AssistantEntry:
    text: str | None
    tool_calls: tuple[ToolCall, ...] = ()
    memory_stamp: MemoryStamp | None = None


@dataclass(frozen=True, slots=True)
class ToolResultEntry:
    call_id: str
    name: str
    payload: Mapping[str, Any]  # JSON-safe envelope or block notice
    is_error: bool = False
    memory_stamp: MemoryStamp | None = None


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
