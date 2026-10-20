"""Chat turn (Role B): the application orchestrates, the language model is a plugin.

1. A decision model classifies the RAW user text (intent + injection) - independent of the LLM.
2. Deterministic gating: injection -> refuse; out of scope -> refuse; medium confidence ->
   clarify; low confidence or no decision model -> read-only (analysis only).
3. The language model picks tools from the registry (only tiers allowed this turn).
4. The reply is verified against the facts returned by the tools. If it fails, it is
   replaced by deterministic narration and the failure is audited.

Memory (ADR-048 §6): a turn that calls a memory tool, or that sees such a turn in its history, is stamped with the
consent generation and memory revision it read. Once either moves (revoked, a declaration confirmed or deleted),
those entries never reach a model again. Dependency propagates: every model request made after memory-derived data
entered the turn is dependent, and so is every tool call it asked for and every result, fact, card and word built on
them; nothing tells an amount the model chose from one it copied from memory, so none of them is assumed independent.
Calls a model asked for before memory entered the turn are independent and keep working.

A turn has two linearization points, both ordered against every memory change by the user's MemoryFence:
- dispatch: before each dependent model request, the counters are checked inside the fence (MemoryUseCases.authorized).
  A change ordered before that check stops the turn there: the request is never sent. A change after it is a change
  during the call: the request may already be on its way and cannot be recalled, and its answer is never published.
  A dependent tool call is not executed once its memory moved either (a plain check before it: a call already
  executed is never rolled back, and none is invented).
- publication: the reply is built whole (narration, verification), then the counters are checked and the history
  written in one step inside the fence (MemoryUseCases.publish_if_current). A change after it comes after the reply:
  the reply carries memory_dependency, and a client that knows newer counters hides all of it.
When memory moved, the reply is MEMORY_CHANGED plus what the independent tools found: no dependent text, fact, card or
action, and nothing dependent is stored, not even unstamped. The user's own message is kept.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from ...domain.actions.terms import Proposal
from ...domain.agent.policy import AgentPolicy, Gate, max_tier_for
from ...domain.agent.questions import Intent
from ...domain.agent.verification import REPAIRABLE_KINDS, VerificationResult, verify_explanation
from ...domain.audit.events import Actor, AuditDraft, AuditKind
from ...domain.permissions.policy import BlockReason
from ...domain.shared.envelope import Caveat, Fact
from ..conversation import (
    AssistantEntry,
    Entry,
    MemoryStamp,
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
from ..services.prompts import SYSTEM_PROMPT, context_block, repair_note
from ..services.tools import ToolContext, ToolOutcome, ToolRegistry
from .actions import ActionOutcome
from .financial import FinancialUseCases
from .memory import MemoryUseCases

MAX_MESSAGE_CHARS = 4000
RECENT_USER_MESSAGES = 3  # how far back an amount the user said still counts for an expense (with this message: 4)


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
    pending_expense: dict | None = None  # an expense prepared from what the user said, for them to confirm (ADR-039)
    pending_memory_proposal: dict | None = None  # a salary prepared from this message, for the user to confirm (ADR-048)
    memory_dependency: dict | None = None  # the memory counters this reply relied on; a client drops it when they move


def _dependency(stamp: MemoryStamp | None) -> dict | None:
    return None if stamp is None else {"consent_generation": stamp[0], "memory_revision": stamp[1]}


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
        memory: MemoryUseCases | None = None,
    ) -> None:
        self._memory = memory
        self._decisions = decisions
        self._llm = language_model
        self._registry = registry
        self._financial = financial
        self._audit = audit
        self._conversations = conversations
        self._clock = clock
        self._ids = ids
        self._policy = policy

    def _record(self, session_id: str, user_id: str, kind: AuditKind, cls: Classification, **fields) -> None:
        self._audit.append(
            AuditDraft(
                event_id=self._ids.new("evt"),
                timestamp=self._clock.now(),
                session_id=session_id,
                user_id=user_id,
                actor=Actor.SYSTEM,
                kind=kind,
                user_intent=cls.intent.value,
                intent_confidence=round(cls.confidence, 4),
                policy_version=self._policy.version,
                decision_model_checks=cls.checks,
                **fields,
            )
        )

    def _short_reply(
        self, session_id: str, user_id: str, user: UserEntry, reply: str, cls: Classification, *, blocked: str | None = None
    ) -> ChatReply:
        self._conversations.append(user_id, session_id, (user, AssistantEntry(reply)), self._policy.history_limit)
        return ChatReply(
            session_id, reply, cls.intent.value, cls.confidence, cls.gate.value, cls.answered_by, None,
            (), (), (), None, False, None, (), blocked,
        )

    def _stamp(self, user_id: str) -> MemoryStamp | None:
        """The memory counters a memory-derived entry stays valid under. Every actual change of the consent moves the
        generation, so equality alone says whether an entry still holds (even one that said memory was off)."""
        if self._memory is None:
            return None
        state = self._memory.consent(user_id)
        return (state.consent_generation, state.memory_revision)

    @staticmethod
    def _without_stale(history: tuple[Entry, ...], current: MemoryStamp | None) -> tuple[Entry, ...]:
        """History as a model may see it: the user's own messages always; a memory-derived assistant or tool entry only
        under the counters it was stamped with. A turn's calls and results share a stamp, so pairs are kept whole."""
        return tuple(
            e for e in history
            if isinstance(e, UserEntry) or e.memory_stamp is None or e.memory_stamp == current
        )

    def handle(self, session_id: str, user_id: str, message: str) -> ChatReply:
        text = message.strip()[:MAX_MESSAGE_CHARS]
        user = UserEntry(text, self._ids.new("msg"))  # the real message's id, before any tool can refer to it
        cls = self._decisions.classify(text)
        self._record(session_id, user_id, AuditKind.DECISION, cls, detail=f"answered_by={cls.answered_by}")

        if cls.injection_flagged:
            self._record(session_id, user_id, AuditKind.INJECTION_FLAGGED, cls, blocked_reason=BlockReason.INJECTION_SUSPECTED.value)
            return self._short_reply(session_id, user_id, user, narration.REFUSAL_INJECTION, cls, blocked=BlockReason.INJECTION_SUSPECTED.value)
        if cls.intent is Intent.OUT_OF_SCOPE and cls.gate is Gate.PROCEED:
            self._record(session_id, user_id, AuditKind.OUT_OF_SCOPE, cls)
            return self._short_reply(session_id, user_id, user, narration.REFUSAL_SCOPE, cls)
        if cls.gate is Gate.CLARIFY:
            self._record(session_id, user_id, AuditKind.CLARIFICATION_REQUESTED, cls)
            return self._short_reply(session_id, user_id, user, narration.CLARIFY, cls)

        max_tier = max_tier_for(cls.gate)
        allow_stateful = cls.gate is Gate.PROCEED
        as_of, currency = self._financial.context(user_id)
        current = self._stamp(user_id)
        history = self._without_stale(self._conversations.history(user_id, session_id), current)
        # A reply that sees memory-derived context derives from it too: it inherits the stamp.
        turn_stamp: MemoryStamp | None = current if any(not isinstance(e, UserEntry) and e.memory_stamp for e in history) else None
        stale = False
        said = [e.text for e in history if isinstance(e, UserEntry)][-RECENT_USER_MESSAGES:]
        ctx = ToolContext(
            session_id, user_id, cls.intent.value, round(cls.confidence, 4), cls.checks, text, "\n".join([*said, text]), user.message_id or ""
        )
        turn_context = TurnContext(cls.intent.value, cls.confidence, cls.gate.value, max_tier.value, as_of, currency)
        system = SYSTEM_PROMPT + context_block(cls.intent.value, cls.confidence, cls.gate.value, max_tier.value, as_of, currency)
        tools = self._registry.specs(max_tier, allow_stateful)

        entries: list[Entry] = [*history, user]
        outcomes: list[ToolOutcome] = []
        final_text: str | None = None
        model_name: str | None = None
        repairs = 0
        discarded: set[int] = set()  # rejected replies and repair notes: shown to the model once, never stored in history

        def check(candidate: str) -> VerificationResult:
            return verify_explanation(
                candidate,
                tuple(f for o in outcomes for f in o.facts),
                tuple(c for o in outcomes for c in o.warnings),
                money_units=frozenset({currency}),
                executions_succeeded=sum(1 for o in outcomes if o.executed),
            )

        dependent: list[bool] = []  # per outcome: asked for by a request that saw memory, or a memory read itself
        for _ in range(self._policy.max_tool_rounds):
            seen = turn_stamp is not None  # this request carries memory-derived context
            if turn_stamp is not None and not self._memory_authorized(user_id, turn_stamp):
                stale = True  # the dispatch boundary: memory moved, so this request is never sent
                break
            request = ModelRequest(system, tuple(entries), tools, turn_context)
            try:
                turn = self._llm.respond(request)
            except LanguageModelUnavailable:
                break
            model_name = turn.model_version
            entries.append(AssistantEntry(turn.text, turn.tool_calls))
            if not turn.tool_calls:
                final_text = turn.text
                if final_text and repairs < self._policy.max_repairs and not any(o.action for o in outcomes):
                    issues = check(final_text).issues
                    if issues and all(i.kind in REPAIRABLE_KINDS for i in issues):
                        # An honest mistake (a figure with no fact behind it, a warning left out): one chance to fix it.
                        self._record(
                            session_id, user_id, AuditKind.VERIFICATION_FAILED, cls,
                            detail="; ".join(f"{i.kind}:{i.detail}" for i in issues)[:480] + " (repair requested)", model_version=model_name,
                        )
                        messages = {c.code: c.message for o in outcomes for c in o.warnings}
                        discarded.add(len(entries) - 1)
                        entries.append(UserEntry(repair_note([(i.kind, i.detail) for i in issues], messages)))
                        discarded.add(len(entries) - 1)
                        final_text = None
                        repairs += 1
                        continue
                break
            for call in turn.tool_calls:
                reads = self._registry.reads_memory(call.name)
                if reads:
                    before = self._stamp(user_id)  # read before the tool: a change after it is caught
                    if turn_stamp is not None and before != turn_stamp:
                        stale = True
                        break
                    turn_stamp = turn_stamp or before
                elif seen and self._stamp(user_id) != turn_stamp:
                    stale = True  # its arguments may come from memory that moved: not executed
                    break
                outcome = self._registry.invoke(call, ctx, max_tier=max_tier, allow_stateful=allow_stateful)
                outcomes.append(outcome)
                dependent.append(seen or reads)
                entries.append(ToolResultEntry(call.call_id, call.name, outcome.payload, outcome.blocked_reason is not None))
            if stale:
                break

        if stale:
            return self._stale_reply(session_id, user_id, user, cls, outcomes, dependent, currency, model_name)

        facts = tuple(f for o in outcomes for f in o.facts)
        caveats = tuple(c for o in outcomes for c in o.warnings)
        deterministic = narration.narrate([(o.name, o.payload) for o in outcomes], currency) if outcomes else None
        fallback = False
        if not final_text:
            final_text = deterministic or (narration.READ_ONLY_NOTE if cls.gate is Gate.READ_ONLY else narration.NO_RESULT)
            fallback = True
        verification = check(final_text)
        if not verification.ok:
            self._record(
                session_id, user_id, AuditKind.VERIFICATION_FAILED, cls,
                detail="; ".join(f"{i.kind}:{i.detail}" for i in verification.issues)[:500], model_version=model_name,
            )
            final_text = deterministic or narration.NO_RESULT
            fallback = True
            verification = check(final_text)
        if cls.gate is Gate.READ_ONLY and cls.intent in (Intent.SAVINGS_PLAN, Intent.SET_LIQUIDITY_FLOOR, Intent.LOG_EXPENSE, Intent.REPORT_INCOME_CHANGE, Intent.EXECUTE_ACTION):
            final_text = f"{final_text} {narration.READ_ONLY_NOTE}"

        turn_entries = [e for i, e in enumerate(entries) if i >= len(history) and i not in discarded]
        if isinstance(turn_entries[-1], AssistantEntry) and not turn_entries[-1].tool_calls:
            turn_entries[-1] = AssistantEntry(final_text)
        else:
            turn_entries.append(AssistantEntry(final_text))
        if turn_stamp is None:
            self._conversations.append(user_id, session_id, turn_entries, self._policy.history_limit)
        else:
            stamped = [e if isinstance(e, UserEntry) else replace(e, memory_stamp=turn_stamp) for e in turn_entries]

            def publish() -> None:
                self._conversations.append(user_id, session_id, stamped, self._policy.history_limit)

            # The publication boundary: the reply is built whole; it is stored, and returned, only if memory still holds.
            if not self._memory_publish(user_id, turn_stamp, publish):
                return self._stale_reply(session_id, user_id, user, cls, outcomes, dependent, currency, model_name)

        proposals = [o.proposal for o in outcomes if o.proposal is not None]
        expenses = [o.payload.get("data") for o in outcomes if o.name == "propose_expense" and o.payload.get("status") == "OK"]
        incomes = [o.payload.get("data") for o in outcomes if o.name == "propose_income_change" and o.payload.get("status") == "OK"]
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
            pending_expense=expenses[-1] if expenses else None,
            pending_memory_proposal=incomes[-1] if incomes else None,
            memory_dependency=_dependency(turn_stamp),
        )

    def _memory_authorized(self, user_id: str, stamp: MemoryStamp) -> bool:
        assert self._memory is not None  # a stamp exists only with memory
        return self._memory.authorized(user_id, stamp)

    def _memory_publish(self, user_id: str, stamp: MemoryStamp, publish: Callable[[], None]) -> bool:
        assert self._memory is not None
        return self._memory.publish_if_current(user_id, stamp, publish)

    def _stale_reply(
        self, session_id: str, user_id: str, user: UserEntry, cls: Classification, outcomes: list[ToolOutcome],
        dependent: list[bool], currency: str, model_name: str | None,
    ) -> ChatReply:
        """The reply when memory moved under the turn: MEMORY_CHANGED and what the independent tools found, narrated
        deterministically. Nothing dependent leaves: not its results, facts, cards, actions or tool names, and not the
        model's text (it may repeat any of them). Only the user's message and this reply are stored, unstamped, since
        neither derives from memory."""
        kept = [o for o, derived in zip(outcomes, dependent, strict=True) if not derived]
        self._record(session_id, user_id, AuditKind.VERIFICATION_FAILED, cls, detail="memory changed during the turn: reply replaced", model_version=model_name)
        text = " ".join(t for t in (narration.narrate([(o.name, o.payload) for o in kept], currency) if kept else "", narration.MEMORY_CHANGED) if t)
        facts = tuple(f for o in kept for f in o.facts)
        caveats = tuple(c for o in kept for c in o.warnings)
        self._conversations.append(user_id, session_id, (user, AssistantEntry(text)), self._policy.history_limit)
        proposals = [o.proposal for o in kept if o.proposal is not None]
        expenses = [o.payload.get("data") for o in kept if o.name == "propose_expense" and o.payload.get("status") == "OK"]
        return ChatReply(
            session_id=session_id, text=text, intent=cls.intent.value, intent_confidence=cls.confidence, gate=cls.gate.value,
            decision_model=cls.answered_by, language_model=model_name, tools_called=tuple(o.name for o in kept), facts=facts,
            warnings=caveats, verification=verify_explanation(text, facts, caveats, money_units=frozenset({currency})), fallback_used=True,
            pending_proposal=proposals[-1] if proposals else None, actions=tuple(o.action for o in kept if o.action is not None),
            blocked_reason=next((o.blocked_reason for o in kept if o.blocked_reason), None),
            pending_expense=expenses[-1] if expenses else None,
        )
