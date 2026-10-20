"""Action use cases (Role C): propose -> user confirms -> execute, each step audited.

- propose: a savings rule's amount comes from the stored plan snapshot, never from model text (decision D7).
  A liquidity floor's amount is what the user wrote: the model may only relay a number that is in the
  user's message of this turn, and the user still confirms the exact terms (ADR-037).
- confirm: ONLY reachable from the UI endpoint. There is no confirm tool for the model.
- execute: terms are re-read from the stored authorization; caller-supplied terms are only
  compared (S03, S05). Expiry (S04), single use (S04, S11) and destination checks (S06) are
  enforced by the deterministic gate. If the audit log cannot record the start of an
  execution, nothing executes (fail closed).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any

from ...domain.actions.terms import (
    ActionTerms,
    Authorization,
    ExecutionReceipt,
    Proposal,
    ProposalStatus,
    terms_for_floor,
    terms_from_plan,
)
from ...domain.agent.amounts import extract_numbers
from ...domain.audit.events import Actor, AuditDraft, AuditKind, DecisionCheck
from ...domain.permissions.policy import (
    BlockReason,
    PermissionPolicy,
    Tier,
    check_execution,
    check_terms,
)
from ...domain.shared.envelope import Fact
from ...domain.shared.errors import InvalidInput
from ...domain.shared.hashing import content_id
from ...domain.shared.month import Month
from ..ports import (
    ActionRepository,
    AuditLog,
    Clock,
    IdGenerator,
    SandboxBank,
    Signer,
    SnapshotStore,
)
from .financial import StoredPlan

_SUPERSEDED = "your financial state changed since this plan was computed; compute the savings plan again"


@dataclass(frozen=True, slots=True)
class ActorContext:
    session_id: str
    user_id: str
    actor: Actor
    user_intent: str | None = None
    intent_confidence: float | None = None
    checks: tuple[DecisionCheck, ...] = ()
    user_text: str = ""


@dataclass(frozen=True, slots=True)
class PublicAuthorization:
    """What leaves the system about an authorization (no signature)."""

    authorization_id: str
    proposal_id: str
    terms: ActionTerms
    expires_at: str
    used: bool


@dataclass(frozen=True, slots=True)
class ActionOutcome:
    status: str  # PROPOSED | CONFIRMED | EXECUTED | FAILED | BLOCKED | INVALID_INPUT | INSUFFICIENT_DATA
    proposal: Proposal | None = None
    authorization: PublicAuthorization | None = None
    receipt: ExecutionReceipt | None = None
    reason: str | None = None
    detail: str | None = None
    field: str | None = None
    authorized_amount: int | None = None
    requested_amount: int | None = None

    def facts(self) -> tuple[Fact, ...]:
        terms = (self.proposal.terms if self.proposal else None) or (self.authorization.terms if self.authorization else None)
        facts: list[Fact] = []
        if terms:
            facts.append(Fact("action.amount", terms.amount, terms.currency, "confirmed or proposed terms"))
        currency = terms.currency if terms else "CLP"
        if self.authorized_amount is not None:
            facts.append(Fact("action.authorized_amount", self.authorized_amount, currency, "stored authorization"))
        if self.requested_amount is not None:
            facts.append(Fact("action.requested_amount", self.requested_amount, currency, "rejected request"))
        return tuple(facts)


@dataclass(frozen=True, slots=True)
class PendingView:
    proposals: tuple[Proposal, ...]
    authorizations: tuple[PublicAuthorization, ...]


def _public(a: Authorization) -> PublicAuthorization:
    return PublicAuthorization(a.authorization_id, a.proposal_id, a.terms, a.expires_at.isoformat(), a.consumed_at is not None)


class ActionUseCases:
    def __init__(
        self,
        snapshots: SnapshotStore,
        repository: ActionRepository,
        bank: SandboxBank,
        audit: AuditLog,
        signer: Signer,
        clock: Clock,
        ids: IdGenerator,
        policy: PermissionPolicy,
        plan_origin: Callable[[str], str | None] | None = None,
    ) -> None:
        """`plan_origin(user_id)` is the origin a plan sized now would carry (FinancialUseCases.plan_origin); with it,
        a plan from a superseded financial state is refused at proposal and at confirmation (UG02, ESMA GL5)."""
        self._plan_origin = plan_origin
        self._snapshots = snapshots
        self._repo = repository
        self._bank = bank
        self._audit = audit
        self._signer = signer
        self._clock = clock
        self._ids = ids
        self._policy = policy

    # ---- audit helper -----------------------------------------------------------------------

    def _record(self, ctx: ActorContext, kind: AuditKind, *, tool: str, tier: Tier, **fields: Any) -> None:
        self._audit.append(
            AuditDraft(
                event_id=self._ids.new("evt"),
                timestamp=self._clock.now(),
                session_id=ctx.session_id,
                user_id=ctx.user_id,
                actor=ctx.actor,
                kind=kind,
                user_intent=ctx.user_intent,
                intent_confidence=ctx.intent_confidence,
                tool_requested=tool,
                policy_version=self._policy.version,
                decision_model_checks=ctx.checks,
                permission_tier=tier.value,
                **fields,
            )
        )

    def _blocked(self, ctx: ActorContext, tool: str, reason: BlockReason, detail: str, tier: Tier = Tier.T2, **extra: Any) -> ActionOutcome:
        self._record(
            ctx,
            AuditKind.ACTION_BLOCKED,
            tool=tool,
            tier=tier,
            blocked_reason=reason.value,
            detail=detail,
            authorization_id=extra.pop("authorization_id", None),
        )
        return ActionOutcome("BLOCKED", reason=reason.value, detail=detail, **extra)

    def _superseded(self, stored: StoredPlan, user_id: str) -> bool:
        return self._plan_origin is not None and stored.origin != self._plan_origin(user_id)

    # ---- propose (T1, stateful, no money moves) ---------------------------------------------

    def propose_savings_rule(self, ctx: ActorContext, plan_snapshot_id: str) -> ActionOutcome:
        tool = "propose_savings_rule"
        stored = self._snapshots.get(str(plan_snapshot_id), ctx.user_id)
        if not isinstance(stored, StoredPlan) or stored.user_id != ctx.user_id:
            return ActionOutcome("INSUFFICIENT_DATA", detail="unknown plan snapshot; compute a savings plan first", field="plan_snapshot_id")
        if self._superseded(stored, ctx.user_id):
            return self._blocked(ctx, tool, BlockReason.PLAN_SUPERSEDED, _SUPERSEDED, Tier.T1)
        try:
            terms = terms_from_plan(stored.plan, stored.currency)
        except InvalidInput as exc:
            return ActionOutcome("INVALID_INPUT", detail=exc.message, field=exc.field)
        gate = check_terms(terms, self._policy)
        if not gate.allowed:
            return self._blocked(ctx, tool, gate.reason, gate.detail, gate.tier)
        now = self._clock.now()
        proposal = Proposal(
            proposal_id=self._ids.new("prop"),
            session_id=ctx.session_id,
            user_id=ctx.user_id,
            terms=terms,
            source_snapshot_id=str(plan_snapshot_id),
            created_at=now,
            expires_at=now + timedelta(seconds=self._policy.proposal_ttl_seconds),
        )
        self._repo.add_proposal(proposal)
        self._record(ctx, AuditKind.PROPOSAL_CREATED, tool=tool, tier=Tier.T1, forecast_snapshot_id=proposal.source_snapshot_id, detail=proposal.proposal_id)
        return ActionOutcome("PROPOSED", proposal=proposal)

    def propose_liquidity_floor(self, ctx: ActorContext, amount: object, first_cycle: Month, currency: str) -> ActionOutcome:
        """The user's own floor (ADR-037). The amount must be one the user wrote in this turn's message."""
        tool = "propose_liquidity_floor"
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            return ActionOutcome("INVALID_INPUT", detail="amount must be a positive integer in minor units", field="amount")
        written = {int(n.value) for n in extract_numbers(ctx.user_text) if not n.is_percent and n.value == int(n.value)}
        if amount not in written:
            return ActionOutcome("INVALID_INPUT", detail="the floor must be an amount the user wrote in this message; ask the user for it", field="amount")
        terms = terms_for_floor(amount, currency, first_cycle)
        gate = check_terms(terms, self._policy)
        if not gate.allowed:
            return self._blocked(ctx, tool, gate.reason, gate.detail, gate.tier)
        now = self._clock.now()
        proposal = Proposal(
            proposal_id=self._ids.new("prop"),
            session_id=ctx.session_id,
            user_id=ctx.user_id,
            terms=terms,
            source_snapshot_id=content_id("floor", ctx.user_id, terms.canonical()),
            created_at=now,
            expires_at=now + timedelta(seconds=self._policy.proposal_ttl_seconds),
        )
        self._repo.add_proposal(proposal)
        self._record(ctx, AuditKind.PROPOSAL_CREATED, tool=tool, tier=Tier.T1, forecast_snapshot_id=proposal.source_snapshot_id, detail=proposal.proposal_id)
        return ActionOutcome("PROPOSED", proposal=proposal)

    # ---- confirm (user only, via UI) ----------------------------------------------------------

    def confirm(self, ctx: ActorContext, proposal_id: str, shown_terms: Mapping[str, Any]) -> ActionOutcome:
        tool = "confirm_action"
        if ctx.actor is not Actor.USER:
            return self._blocked(ctx, tool, BlockReason.SELF_ESCALATION, "only the user can confirm", Tier.T3)
        proposal = self._repo.get_proposal(str(proposal_id))
        if proposal is None or proposal.user_id != ctx.user_id:
            return self._blocked(ctx, tool, BlockReason.PROPOSAL_NOT_FOUND, "no such proposal")
        now = self._clock.now()
        if proposal.status is not ProposalStatus.PENDING:
            return self._blocked(ctx, tool, BlockReason.PROPOSAL_NOT_PENDING, f"proposal is {proposal.status.value}")
        if now >= proposal.expires_at:
            return self._blocked(ctx, tool, BlockReason.PROPOSAL_EXPIRED, "proposal expired")
        stored = self._snapshots.get(proposal.source_snapshot_id, ctx.user_id)
        if isinstance(stored, StoredPlan) and self._superseded(stored, ctx.user_id):
            return self._blocked(ctx, tool, BlockReason.PLAN_SUPERSEDED, _SUPERSEDED)
        try:
            shown = ActionTerms.from_primitive(shown_terms)
        except InvalidInput as exc:
            return ActionOutcome("INVALID_INPUT", detail=exc.message, field=exc.field)
        if shown.canonical() != proposal.terms.canonical():
            return self._blocked(
                ctx, tool, BlockReason.TERMS_CHANGED, "terms shown differ from the proposal",
                authorized_amount=proposal.terms.amount, requested_amount=shown.amount,
            )
        authorization = Authorization(
            authorization_id=self._ids.new("auth"),
            proposal_id=proposal.proposal_id,
            session_id=proposal.session_id,
            user_id=ctx.user_id,
            terms=proposal.terms,
            action_hash=self._signer.sign(proposal.terms.canonical()),
            created_at=now,
            expires_at=now + timedelta(seconds=self._policy.authorization_ttl_seconds),
        )
        self._repo.add_authorization(authorization)
        self._repo.update_proposal(replace(proposal, status=ProposalStatus.CONFIRMED))
        self._record(ctx, AuditKind.ACTION_CONFIRMED, tool=tool, tier=Tier.T2, authorization_id=authorization.authorization_id, forecast_snapshot_id=proposal.source_snapshot_id)
        return ActionOutcome("CONFIRMED", proposal=replace(proposal, status=ProposalStatus.CONFIRMED), authorization=_public(authorization))

    # ---- execute (T2) -------------------------------------------------------------------------

    def execute(self, ctx: ActorContext, authorization_id: str, requested_terms: Mapping[str, Any] | None = None) -> ActionOutcome:
        tool = "execute_sandbox_action"
        requested = None
        if requested_terms:
            try:
                requested = ActionTerms.from_primitive(requested_terms)
            except InvalidInput as exc:
                return self._blocked(ctx, tool, BlockReason.AUTHORIZATION_MISMATCH, f"malformed requested terms: {exc.message}")
        authorization = self._repo.get_authorization(str(authorization_id))
        signature_ok = authorization is not None and self._signer.verify(authorization.terms.canonical(), authorization.action_hash)
        now = self._clock.now()
        decision = check_execution(
            authorization, user_id=ctx.user_id, requested=requested, now=now, policy=self._policy, signature_valid=signature_ok
        )
        if not decision.allowed:
            extra: dict[str, Any] = {"authorization_id": str(authorization_id)}
            if decision.reason is BlockReason.AUTHORIZATION_MISMATCH and authorization and requested:
                extra.update(authorized_amount=authorization.terms.amount, requested_amount=requested.amount)
            return self._blocked(ctx, tool, decision.reason, decision.detail, decision.tier, **extra)
        assert authorization is not None
        try:
            self._record(ctx, AuditKind.EXECUTION_STARTED, tool=tool, tier=Tier.T2, authorization_id=authorization.authorization_id)
        except Exception:  # noqa: BLE001 - any audit failure must stop execution
            return ActionOutcome("BLOCKED", reason=BlockReason.AUDIT_UNAVAILABLE.value, detail="audit log unavailable")
        if not self._repo.consume_authorization(authorization.authorization_id, now):
            return self._blocked(ctx, tool, BlockReason.AUTHORIZATION_REPLAYED, "authorization already used", authorization_id=authorization.authorization_id)
        execution_id = self._ids.new("exec")
        receipt = self._bank.create_savings_rule(ctx.user_id, authorization.terms, authorization.authorization_id, execution_id)
        public = _public(replace(authorization, consumed_at=now))
        if receipt.ok:
            self._record(ctx, AuditKind.ACTION_EXECUTED, tool=tool, tier=Tier.T2, authorization_id=authorization.authorization_id, execution_result=f"OK:{receipt.reference}")
            return ActionOutcome("EXECUTED", authorization=public, receipt=receipt)
        self._record(ctx, AuditKind.ACTION_FAILED, tool=tool, tier=Tier.T2, authorization_id=authorization.authorization_id, execution_result=f"FAILED:{receipt.error}")
        return ActionOutcome("FAILED", authorization=public, receipt=receipt, detail=receipt.error)

    # ---- read ---------------------------------------------------------------------------------

    def pending(self, ctx: ActorContext) -> PendingView:
        now = self._clock.now()
        proposals, authorizations = self._repo.for_session(ctx.session_id)
        return PendingView(
            proposals=tuple(p for p in proposals if p.user_id == ctx.user_id and p.status is ProposalStatus.PENDING and now < p.expires_at),
            authorizations=tuple(
                _public(a) for a in authorizations if a.user_id == ctx.user_id and a.consumed_at is None and not a.is_expired(now)
            ),
        )
