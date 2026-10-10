"""Chat turn (Role B): the application orchestrates, the language model is a plugin.

1. A decision model classifies the RAW user text (intent + injection) - independent of the LLM.
2. Deterministic gating: injection -> refuse; out of scope -> refuse; medium confidence ->
   clarify; low confidence or no decision model -> read-only (analysis only).
3. The language model picks tools from the registry (only tiers allowed this turn).
4. The reply is verified against the facts returned by the tools. If it fails, it is
   replaced by deterministic narration and the failure is audited.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...domain.actions.terms import Proposal
from ...domain.agent.policy import AgentPolicy, Gate, max_tier_for
from ...domain.agent.questions import Intent
from ...domain.agent.verification import VerificationResult, verify_explanation
from ...domain.audit.events import Actor, AuditDraft, AuditKind
from ...domain.permissions.policy import BlockReason
from ...domain.shared.envelope import Caveat, Fact
from ..conversation import (
    AssistantEntry,
    Entry,
    ModelRequest,
    ToolResultEntry,
    TurnContext,
    UserEntry,
)
from ..ports import (
    AuditLog,
    Clock,
    ConversationStore,
    IdGenerator,
    LanguageModel,
    LanguageModelUnavailable,
)
from ..services import narration
from ..services.decisions import Classification, DecisionService
from ..services.prompts import SYSTEM_PROMPT, context_block
from ..services.tools import ToolContext, ToolOutcome, ToolRegistry
from .actions import ActionOutcome
from .financial import FinancialUseCases

MAX_MESSAGE_CHARS = 4000


@dataclass(frozen=True)
class ChatReply:
    session_id: str
    text: str
    intent: str
    intent_confidence: float
    gate: str
    decision_model: str | None
    language_model: str | None
    tools_called: tuple[str, ...]
    facts: tuple[Fact, ...]
    warnings: tuple[Caveat, ...]
    verification: VerificationResult | None
    fallback_used: bool
    pending_proposal: Proposal | None
    actions: tuple[ActionOutcome, ...]
    blocked_reason: str | None


class ChatUseCase:
    def __init__(
        self,
        decisions: DecisionService,
        language_model: LanguageModel,
        registry: ToolRegistry,
        financial: FinancialUseCases,
        audit: AuditLog,
        conversations: ConversationStore,
        clock: Clock,
        ids: IdGenerator,
        policy: AgentPolicy,
    ) -> None:
        self._decisions = decisions
        self._llm = language_model
        self._registry = registry
        self._financial = financial
        self._audit = audit
        self._conversations = conversations
        self._clock = clock
        self._ids = ids
        self._policy = policy

    def _record(self, session_id: str, kind: AuditKind, cls: Classification, **fields) -> None:
        self._audit.append(
            AuditDraft(
                event_id=self._ids.new("evt"),
                timestamp=self._clock.now(),
                session_id=session_id,
                actor=Actor.SYSTEM,
                kind=kind,
                user_intent=cls.intent.value,
                intent_confidence=round(cls.confidence, 4),
                policy_version=self._policy.version,
                decision_model_checks=cls.checks,
                **fields,
            )
        )

    def _short_reply(self, session_id: str, user_text: str, reply: str, cls: Classification, *, blocked: str | None = None) -> ChatReply:
        self._conversations.append(session_id, (UserEntry(user_text), AssistantEntry(reply)), self._policy.history_limit)
        return ChatReply(
            session_id, reply, cls.intent.value, cls.confidence, cls.gate.value, cls.answered_by, None,
            (), (), (), None, False, None, (), blocked,
        )

    def handle(self, session_id: str, user_id: str, message: str) -> ChatReply:
        text = message.strip()[:MAX_MESSAGE_CHARS]
        cls = self._decisions.classify(text)
        self._record(session_id, AuditKind.DECISION, cls, detail=f"answered_by={cls.answered_by}")

        if cls.injection_flagged:
            self._record(session_id, AuditKind.INJECTION_FLAGGED, cls, blocked_reason=BlockReason.INJECTION_SUSPECTED.value)
            return self._short_reply(session_id, text, narration.REFUSAL_INJECTION, cls, blocked=BlockReason.INJECTION_SUSPECTED.value)
        if cls.intent is Intent.OUT_OF_SCOPE and cls.gate is Gate.PROCEED:
            self._record(session_id, AuditKind.OUT_OF_SCOPE, cls)
            return self._short_reply(session_id, text, narration.REFUSAL_SCOPE, cls)
        if cls.gate is Gate.CLARIFY:
            self._record(session_id, AuditKind.CLARIFICATION_REQUESTED, cls)
            return self._short_reply(session_id, text, narration.CLARIFY, cls)

        max_tier = max_tier_for(cls.gate)
        allow_stateful = cls.gate is Gate.PROCEED
        as_of, currency = self._financial.context(user_id)
        ctx = ToolContext(session_id, user_id, cls.intent.value, round(cls.confidence, 4), cls.checks)
        turn_context = TurnContext(cls.intent.value, cls.confidence, cls.gate.value, max_tier.value, as_of, currency)
        system = SYSTEM_PROMPT + context_block(cls.intent.value, cls.confidence, cls.gate.value, max_tier.value, as_of, currency)
        tools = self._registry.specs(max_tier, allow_stateful)

        history = self._conversations.history(session_id)
        entries: list[Entry] = [*history, UserEntry(text)]
        outcomes: list[ToolOutcome] = []
        final_text: str | None = None
        model_name: str | None = None
        for _ in range(self._policy.max_tool_rounds):
            request = ModelRequest(system, tuple(entries), tools, turn_context)
            try:
                turn = self._llm.respond(request)
            except LanguageModelUnavailable:
                break
            model_name = turn.model_version
            entries.append(AssistantEntry(turn.text, turn.tool_calls))
            if not turn.tool_calls:
                final_text = turn.text
                break
            for call in turn.tool_calls:
                outcome = self._registry.invoke(call, ctx, max_tier=max_tier, allow_stateful=allow_stateful)
                outcomes.append(outcome)
                entries.append(ToolResultEntry(call.call_id, call.name, outcome.payload, outcome.blocked_reason is not None))

        facts = tuple(f for o in outcomes for f in o.facts)
        caveats = tuple(c for o in outcomes for c in o.warnings)
        executed = sum(1 for o in outcomes if o.executed)
        deterministic = narration.narrate([(o.name, o.payload) for o in outcomes], currency) if outcomes else None
        fallback = False
        if not final_text:
            final_text = deterministic or (narration.READ_ONLY_NOTE if cls.gate is Gate.READ_ONLY else narration.NO_RESULT)
            fallback = True
        verification = verify_explanation(final_text, facts, caveats, money_units=frozenset({currency}), executions_succeeded=executed)
        if not verification.ok:
            self._record(
                session_id, AuditKind.VERIFICATION_FAILED, cls,
                detail="; ".join(f"{i.kind}:{i.detail}" for i in verification.issues)[:500], model_version=model_name,
            )
            final_text = deterministic or narration.NO_RESULT
            fallback = True
            verification = verify_explanation(final_text, facts, caveats, money_units=frozenset({currency}), executions_succeeded=executed)
        if cls.gate is Gate.READ_ONLY and cls.intent in (Intent.SAVINGS_PLAN, Intent.EXECUTE_ACTION):
            final_text = f"{final_text} {narration.READ_ONLY_NOTE}"

        turn_entries = entries[len(history):]
        if isinstance(turn_entries[-1], AssistantEntry) and not turn_entries[-1].tool_calls:
            turn_entries[-1] = AssistantEntry(final_text)
        else:
            turn_entries.append(AssistantEntry(final_text))
        self._conversations.append(session_id, turn_entries, self._policy.history_limit)

        proposals = [o.proposal for o in outcomes if o.proposal is not None]
        blocked = next((o.blocked_reason for o in outcomes if o.blocked_reason), None)
        return ChatReply(
            session_id=session_id,
            text=final_text,
            intent=cls.intent.value,
            intent_confidence=cls.confidence,
            gate=cls.gate.value,
            decision_model=cls.answered_by,
            language_model=model_name,
            tools_called=tuple(o.name for o in outcomes),
            facts=facts,
            warnings=caveats,
            verification=verification,
            fallback_used=fallback,
            pending_proposal=proposals[-1] if proposals else None,
            actions=tuple(o.action for o in outcomes if o.action is not None),
            blocked_reason=blocked,
        )
