"""The agent's tool catalog: tool name -> tier -> use case. Tiers are fixed here, in code.

Changes from Spec v0 (see docs/DECISIONS.md):
  * create_savings_rule(...) with free parameters is replaced by propose_savings_rule(plan_snapshot_id).
  * propose_plan is split into derive_permitted_profile + compute_savings_plan (Financial Core section 7).
  * verify_recommendation is not a tool: verification runs on every reply automatically.
  * get_pending_actions is new (T0) so the agent can find the authorization the user confirmed.
  * get_transactions arrives with the ledger-backed model source (Role C).
  * search_financial_concepts (T0) explains a term from the concept cards (ADR-040).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..domain.agent.amounts import parse_income_statement
from ..domain.audit.events import Actor
from ..domain.memory.catalog import CATALOG_VERSION, ChatOrigin
from ..domain.memory.proposals import MemoryProposal, ReadAs
from ..domain.memory.salary_check import CHECKER_VERSION
from ..domain.permissions.policy import Tier
from ..domain.shared.envelope import Envelope, Fact
from ..domain.shared.errors import InvalidInput
from .ports import AuditLog, Clock, IdGenerator
from .services.tools import Tool, ToolContext, ToolDefinition, ToolRegistry
from .use_cases.actions import ActionUseCases, ActorContext
from .use_cases.audit import AuditUseCases
from .use_cases.connections import ConnectionUseCases
from .use_cases.documents import DocumentUseCases
from .use_cases.education import EducationUseCases
from .use_cases.financial import FinancialUseCases
from .use_cases.investments import InvestmentUseCases
from .use_cases.memory import MemoryUseCases
from .use_cases.profile import ProfileUseCases


def _int(args: Mapping[str, Any], name: str, default: int) -> int:
    value = args.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise InvalidInput(name, f"{name} must be an integer")
    return int(value)


def _str(args: Mapping[str, Any], name: str, default: str | None = None) -> str | None:
    value = args.get(name, default)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidInput(name, f"{name} must be a string")
    return value


def _required(args: Mapping[str, Any], name: str) -> Any:
    if name not in args or args[name] is None:
        raise InvalidInput(name, f"{name} is required")
    return args[name]


def _actor(ctx: ToolContext) -> ActorContext:
    return ActorContext(ctx.session_id, ctx.user_id, Actor.AGENT, ctx.intent, ctx.intent_confidence, ctx.checks, ctx.user_text)


def _connected(connections: ConnectionUseCases | None, ctx: ToolContext) -> Any:
    if connections is None:
        raise InvalidInput("connection", "connections are not available on this server")
    return connections.connected_data(ctx.user_id)


def _propose_floor(financial: FinancialUseCases, actions: ActionUseCases, args: Mapping[str, Any], ctx: ToolContext) -> Any:
    cycle = financial.first_cycle(ctx.user_id)
    if not isinstance(cycle, tuple):
        return cycle  # INSUFFICIENT_DATA envelope: no financial model for this user
    return actions.propose_liquidity_floor(_actor(ctx), _required(args, "amount"), *cycle)


def _no_arguments(args: Mapping[str, Any]) -> None:
    """The memory tools take nothing from the model: an amount, a month or anything else is refused at run time, not
    only by the schema. The field never echoes what was sent."""
    if args:
        raise InvalidInput("arguments", "this tool takes no arguments; the salary is read only from the user's message")


def proposal_view(p: MemoryProposal) -> dict[str, Any]:
    """contracts/memory/income_proposal.schema.json: what the card shows and the model may read."""
    return {
        "proposal_id": p.proposal_id, "status": p.status.value, "candidates": list(p.candidates),
        "effective_from": {"pay_month": str(p.effective_from), "read_as": p.read_as.value}, "needs_base": p.needs_base,
        "chain_id": p.chain_id, "expected_version": p.expected_version, "currency": "CLP",
    }


def _propose_income(memory: MemoryUseCases, clock: Clock, args: Mapping[str, Any], ctx: ToolContext) -> Any:
    _no_arguments(args)
    if memory.is_persona(ctx.user_id):
        raise InvalidInput("user", "a shared demo profile keeps no memory")
    if not ctx.message_id:
        raise InvalidInput("message", "there is no message of the user to read a salary from")
    today = clock.now().date()
    # The message that started this turn, and only it: never an earlier message, a repair note or a model's text.
    read = parse_income_statement(ctx.user_text, today)
    outcome = memory.prepare(ctx.user_id, ChatOrigin(ctx.session_id, ctx.message_id), read.candidates, read.pay_month, ReadAs(read.read_as))
    if outcome.status == "CONSENT_REQUIRED":
        return Envelope.insufficient(("memory_consent",), params_version=CATALOG_VERSION, message="the user has not turned on memory")
    if not outcome.ok or outcome.proposal is None:
        return Envelope.invalid("proposal", (), params_version=CATALOG_VERSION, message="the proposal could not be prepared; ask again")
    proposal = outcome.proposal
    facts = tuple(
        Fact(f"memory.proposal.candidate_{i + 1}", amount, "CLP", "an amount read from the user's message; not saved")
        for i, amount in enumerate(proposal.candidates)
    )
    return Envelope.success(
        proposal_view(proposal), params_version=CATALOG_VERSION, snapshot_id=proposal.proposal_id, as_of=today.isoformat(), facts=facts,
    )


def _user_memory(memory: MemoryUseCases, clock: Clock, args: Mapping[str, Any], ctx: ToolContext) -> Any:
    _no_arguments(args)
    summary, _ = memory.summary(ctx.user_id)
    facts: list[Fact] = []
    for i, item in enumerate(summary["items"], start=1):
        facts.append(Fact(f"memory.salary_net_{i}.amount", item["amount"], "CLP", "declared by the user, never a credited salary"))
        facts.append(Fact(f"memory.salary_net_{i}.status", item["status"], "status", f"derived from the statements ({CHECKER_VERSION})"))
        if item["upcoming"] is not None:
            facts.append(Fact(f"memory.salary_net_{i}.upcoming_amount", item["upcoming"]["amount"], "CLP", "declared, from a later pay month"))
    return Envelope.success(
        summary, params_version=CHECKER_VERSION, snapshot_id=f"memory_{summary['consent']}_{len(summary['items'])}",
        as_of=clock.now().date().isoformat(), facts=tuple(facts),
    )


def build_registry(
    financial: FinancialUseCases,
    actions: ActionUseCases,
    profiles: ProfileUseCases,
    audit_queries: AuditUseCases,
    documents: DocumentUseCases,
    investments: InvestmentUseCases,
    education: EducationUseCases,
    definitions: Mapping[str, ToolDefinition],
    audit: AuditLog,
    clock: Clock,
    ids: IdGenerator,
    policy_version: str,
    connections: ConnectionUseCases | None = None,
    memory: MemoryUseCases | None = None,
) -> ToolRegistry:
    memory_tools: tuple[Tool, ...] = ()
    if memory is not None:  # ADR-048: saved only; no tool confirms, edits, deletes or consents
        memory_tools = (
            Tool("get_user_memory", Tier.T0, lambda a, c: _user_memory(memory, clock, a, c), reads_memory=True),
            Tool("propose_income_change", Tier.T1, lambda a, c: _propose_income(memory, clock, a, c), stateful=True, reads_memory=True),
        )
    tools = (
        # T0: read
        Tool("get_financial_state", Tier.T0, lambda a, c: financial.financial_state(c.user_id)),
        Tool("get_commitments", Tier.T0, lambda a, c: financial.commitments(c.user_id, _int(a, "horizon_months", 6))),
        Tool("get_user_profile", Tier.T0, lambda a, c: profiles.user_profile(c.user_id)),
        Tool("get_pending_actions", Tier.T0, lambda a, c: actions.pending(_actor(c))),
        # The last synced snapshot of the linked investment account (ADR-044). Linking and syncing are not tools (S31).
        Tool("get_investments", Tier.T0, lambda a, c: investments.overview(c.user_id)),
        Tool(
            "get_audit_events",
            Tier.T0,
            lambda a, c: audit_queries.events(c.user_id, c.session_id, _int(a, "limit", 50)),
        ),
        Tool("get_spending_status", Tier.T0, lambda a, c: documents.spending_status(c.user_id)),
        Tool("get_latest_document", Tier.T0, lambda a, c: documents.latest_document(c.user_id)),
        # Education (ADR-040): retrieval over the team's concept cards; validated in the use case, never advice.
        Tool(
            "search_financial_concepts",
            Tier.T0,
            lambda a, c: education.explain(c.user_id, a.get("query"), a.get("lang"), a.get("k", 3)),
        ),
        # Reads what the user's last sync stored; nothing reaches a connected service from here (ADR-047).
        Tool("get_connected_data", Tier.T0, lambda a, c: _connected(connections, c)),
        # T1: analyze and suggest
        Tool(
            "forecast_cashflow",
            Tier.T1,
            lambda a, c: financial.forecast(
                c.user_id, _int(a, "horizon_months", 6), _str(a, "scenario", "conservative"), _str(a, "include_plan", "none")
            ),
        ),
        Tool(
            "simulate_purchase",
            Tier.T1,
            lambda a, c: financial.simulate_purchase(
                c.user_id,
                _required(a, "amount"),
                _required(a, "installments"),
                _str(a, "first_installment_month"),
                a.get("monthly_rate"),
                _str(a, "include_plan", "none"),
            ),
        ),
        Tool(
            "compute_protected_surplus",
            Tier.T1,
            lambda a, c: financial.protected_surplus(c.user_id, _int(a, "horizon_months", 6), _str(a, "include_plan", "none")),
        ),
        Tool("assess_financial_capacity", Tier.T1, lambda a, c: financial.capacity(c.user_id)),
        Tool("assess_risk_tolerance", Tier.T1, lambda a, c: profiles.risk_tolerance(c.user_id, c.session_id)),
        Tool(
            "derive_permitted_profile",
            Tier.T1,
            lambda a, c: financial.permitted_profile(c.user_id, str(_required(a, "tolerance"))),
        ),
        Tool("compute_savings_plan", Tier.T1, lambda a, c: financial.savings_plan(c.user_id, _str(a, "permitted_profile"))),
        Tool(
            "propose_savings_rule",
            Tier.T1,
            lambda a, c: actions.propose_savings_rule(_actor(c), str(_required(a, "plan_snapshot_id"))),
            stateful=True,
        ),
        Tool("propose_liquidity_floor", Tier.T1, lambda a, c: _propose_floor(financial, actions, a, c), stateful=True),
        Tool(
            "propose_expense",
            Tier.T1,
            lambda a, c: documents.propose_expense(
                c.user_id, c.recent_user_text or c.user_text, a.get("amount"), a.get("description"), a.get("category"), a.get("payment"), a.get("spent_on")
            ),
            stateful=True,
        ),
        # T2: execute an approved sandbox action (terms come from the stored authorization)
        Tool(
            "execute_sandbox_action",
            Tier.T2,
            lambda a, c: actions.execute(_actor(c), str(_required(a, "authorization_id")), a.get("requested_terms")),
        ),
        *memory_tools,
    )
    return ToolRegistry(tools, definitions, audit, clock, ids, policy_version)
