"""Tool registry: the ONLY capabilities a language model can reach.

Each tool has a tier fixed in code. Calls to unknown or prohibited names are blocked as T3
and audited. Tools above the turn's max tier are hidden and, if called anyway, blocked.
Descriptions and input schemas come from contracts/tools/*.input.schema.json.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ...domain.actions.terms import Proposal
from ...domain.audit.events import Actor, AuditDraft, AuditKind, DecisionCheck
from ...domain.permissions.policy import PROHIBITED_CAPABILITIES, BlockReason, Tier
from ...domain.shared.envelope import Caveat, Envelope, Fact
from ...domain.shared.errors import InvalidInput
from ...domain.shared.hashing import canonical_json, sha256_hex
from ...domain.shared.serialization import to_primitive
from ..conversation import ToolCall, ToolSpec
from ..ports import AuditLog, Clock, IdGenerator
from ..use_cases.actions import ActionOutcome


@dataclass(frozen=True, slots=True)
class ToolContext:
    session_id: str
    user_id: str
    intent: str | None = None
    intent_confidence: float | None = None
    checks: tuple[DecisionCheck, ...] = ()


Handler = Callable[[Mapping[str, Any], ToolContext], Any]


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    tier: Tier
    handler: Handler
    stateful: bool = False  # creates state (e.g. a proposal): hidden in read-only turns


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """From contracts: what the model is told about the tool."""

    description: str
    input_schema: Mapping[str, Any]


@dataclass(frozen=True)
class ToolOutcome:
    name: str
    payload: dict[str, Any]
    tier: Tier
    facts: tuple[Fact, ...] = ()
    warnings: tuple[Caveat, ...] = ()
    blocked_reason: str | None = None
    proposal: Proposal | None = None
    action: ActionOutcome | None = None
    snapshot_id: str | None = None
    executed: bool = False


class ToolRegistry:
    def __init__(
        self,
        tools: tuple[Tool, ...],
        definitions: Mapping[str, ToolDefinition],
        audit: AuditLog,
        clock: Clock,
        ids: IdGenerator,
        policy_version: str,
    ) -> None:
        missing = sorted(t.name for t in tools if t.name not in definitions)
        if missing:
            raise ValueError(f"tools without a contract in contracts/tools: {missing}")
        self._tools = {t.name: t for t in tools}
        self._definitions = definitions
        self._audit = audit
        self._clock = clock
        self._ids = ids
        self._policy_version = policy_version

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def tier_of(self, name: str) -> Tier | None:
        tool = self._tools.get(name)
        return tool.tier if tool else None

    def specs(self, max_tier: Tier, allow_stateful: bool) -> tuple[ToolSpec, ...]:
        return tuple(
            ToolSpec(t.name, self._definitions[t.name].description, self._definitions[t.name].input_schema, t.tier.value)
            for t in sorted(self._tools.values(), key=lambda t: t.name)
            if t.tier.rank <= max_tier.rank and (allow_stateful or not t.stateful)
        )

    def _audit_event(self, ctx: ToolContext, kind: AuditKind, name: str, tier: Tier, params_hash: str, **fields: Any) -> None:
        self._audit.append(
            AuditDraft(
                event_id=self._ids.new("evt"),
                timestamp=self._clock.now(),
                session_id=ctx.session_id,
                user_id=ctx.user_id,
                actor=Actor.AGENT,
                kind=kind,
                user_intent=ctx.intent,
                intent_confidence=ctx.intent_confidence,
                tool_requested=name,
                tool_parameters_hash=params_hash,
                policy_version=self._policy_version,
                decision_model_checks=ctx.checks,
                permission_tier=tier.value,
                **fields,
            )
        )

    def invoke(self, call: ToolCall, ctx: ToolContext, *, max_tier: Tier, allow_stateful: bool) -> ToolOutcome:
        params_hash = sha256_hex(canonical_json(dict(call.arguments)))
        tool = self._tools.get(call.name)
        if tool is None:
            reason = PROHIBITED_CAPABILITIES.get(call.name, BlockReason.UNKNOWN_TOOL)
            return self._block(call.name, ctx, Tier.T3, reason, params_hash, "capability not available to the agent")
        if tool.tier.rank > max_tier.rank or (tool.stateful and not allow_stateful):
            return self._block(call.name, ctx, tool.tier, BlockReason.TIER_NOT_ALLOWED, params_hash, f"max tier this turn is {max_tier.value}")

        try:
            result = tool.handler(call.arguments, ctx)
        except InvalidInput as exc:
            result = Envelope.invalid(exc.field, exc.allowed, params_version=self._policy_version, message=exc.message)

        if isinstance(result, ActionOutcome):
            payload: dict[str, Any] = {"status": result.status, "outcome": to_primitive(result), "facts": to_primitive(result.facts())}
            if result.status == "INVALID_INPUT":
                payload.update(field=result.field, message=result.detail)
            if result.status == "INSUFFICIENT_DATA":
                payload.update(missing=[result.field or "data"], message=result.detail)
            # actions audit themselves in ActionUseCases; record the tool call for completeness
            self._audit_event(ctx, AuditKind.TOOL_CALL, call.name, tool.tier, params_hash, execution_result=result.status, blocked_reason=result.reason)
            return ToolOutcome(
                call.name, payload, tool.tier, facts=result.facts(), blocked_reason=result.reason,
                proposal=result.proposal if result.status == "PROPOSED" else None, action=result,
                executed=result.status == "EXECUTED",
            )

        if isinstance(result, Envelope):
            payload = to_primitive(result)
            self._audit_event(
                ctx, AuditKind.TOOL_CALL, call.name, tool.tier, params_hash,
                forecast_snapshot_id=result.snapshot_id, execution_result=result.status.value,
            )
            return ToolOutcome(call.name, payload, tool.tier, facts=result.facts, warnings=result.warnings, snapshot_id=result.snapshot_id)

        payload = {"status": "OK", "data": to_primitive(result), "facts": []}
        self._audit_event(ctx, AuditKind.TOOL_CALL, call.name, tool.tier, params_hash, execution_result="OK")
        return ToolOutcome(call.name, payload, tool.tier)

    def _block(self, name: str, ctx: ToolContext, tier: Tier, reason: BlockReason, params_hash: str, detail: str) -> ToolOutcome:
        self._audit_event(ctx, AuditKind.ACTION_BLOCKED, name, tier, params_hash, blocked_reason=reason.value, detail=detail)
        payload = {"status": "BLOCKED", "reason": reason.value, "tier": tier.value, "detail": detail}
        return ToolOutcome(name, payload, tier, blocked_reason=reason.value)
