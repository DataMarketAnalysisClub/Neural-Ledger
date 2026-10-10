"""Build the application from settings. The ONLY module that chooses concrete adapters."""

from __future__ import annotations

import warnings
from dataclasses import dataclass

from ..adapters.outbound.bank.simulated import SimulatedSandboxBank
from ..adapters.outbound.decision.jev import JevDecisionModel
from ..adapters.outbound.decision.rules import RulesDecisionModel
from ..adapters.outbound.fixtures.ledger_source import LedgerModelSource
from ..adapters.outbound.fixtures.persona_source import PersonaFixtureSource
from ..adapters.outbound.llm.anthropic import AnthropicLanguageModel
from ..adapters.outbound.llm.scripted import ScriptedLanguageModel
from ..adapters.outbound.persistence.memory import (
    InMemoryActionRepository,
    InMemoryAuditLog,
    InMemoryConversationStore,
    InMemorySavingsRuleStore,
    InMemorySnapshotStore,
    InMemoryUserProfileStore,
)
from ..adapters.outbound.persistence.sqlite import (
    SqliteActionRepository,
    SqliteAuditLog,
    SqliteDatabase,
    SqliteSavingsRuleStore,
)
from ..adapters.outbound.system.clock import FixedClock, SystemClock
from ..adapters.outbound.system.ids import SequentialIds, UuidIds
from ..adapters.outbound.system.signer import HmacSigner
from ..application.catalog import build_registry
from ..application.facade import ApplicationServices
from ..application.services.decisions import DecisionService
from ..application.services.llm_fallback import FallbackLanguageModel
from ..application.use_cases.actions import ActionUseCases
from ..application.use_cases.audit import AuditUseCases
from ..application.use_cases.chat import ChatUseCase
from ..application.use_cases.financial import FinancialUseCases
from ..application.use_cases.profile import ProfileUseCases
from ..domain.agent.policy import AP_0_1
from ..domain.finance.params import FC_0_1
from ..domain.permissions.policy import PP_0_1
from .config import DEV_SECRET, Settings
from .contracts import load_tool_definitions


@dataclass
class Adapters:
    """Concrete adapters, exposed for tests (e.g. to inject a bank failure or advance the clock)."""

    clock: FixedClock | SystemClock
    bank: SimulatedSandboxBank
    actions_repo: InMemoryActionRepository | SqliteActionRepository
    audit_log: InMemoryAuditLog | SqliteAuditLog
    source: PersonaFixtureSource | LedgerModelSource


def build(settings: Settings | None = None) -> tuple[ApplicationServices, Adapters]:
    s = settings or Settings.from_env()
    if s.hmac_secret == DEV_SECRET and s.mode == "live":
        warnings.warn("NL_HMAC_SECRET is the development default; set a real secret", stacklevel=2)

    clock = FixedClock(s.fixed_instant) if s.clock == "fixed" else SystemClock()
    ids = SequentialIds() if s.ids == "sequential" else UuidIds()
    signer = HmacSigner(s.hmac_secret)

    personas = PersonaFixtureSource(s.resolved_data_dir / "personas")  # golden reference + typed user records
    if s.model_source == "fixture":
        source: PersonaFixtureSource | LedgerModelSource = personas
    elif s.model_source == "ledger":
        source = LedgerModelSource(s.resolved_data_dir / "ledgers", FC_0_1)  # stage-1 estimators over the ledger
    else:
        raise ValueError(f"unknown NL_MODEL_SOURCE {s.model_source!r} (fixture | ledger)")

    if s.persistence == "sqlite":
        db = SqliteDatabase(s.sqlite_path)
        actions_repo: InMemoryActionRepository | SqliteActionRepository = SqliteActionRepository(db)
        audit_log: InMemoryAuditLog | SqliteAuditLog = SqliteAuditLog(db)
        rule_store: InMemorySavingsRuleStore | SqliteSavingsRuleStore = SqliteSavingsRuleStore(db)
    else:
        actions_repo, audit_log, rule_store = InMemoryActionRepository(), InMemoryAuditLog(), InMemorySavingsRuleStore()

    snapshots = InMemorySnapshotStore()
    conversations = InMemoryConversationStore()
    bank = SimulatedSandboxBank(rule_store)
    profiles = InMemoryUserProfileStore([personas.profile(name) for name in personas.user_ids()])

    models = []
    for name in s.decision_chain:
        if name == "rules":
            models.append(RulesDecisionModel())
        elif name == "jev":
            models.append(JevDecisionModel(s.typesafe_api_key, s.jev_model))
        else:
            raise ValueError(f"unknown decision model {name!r} in NL_DECISION_CHAIN")
    decisions = DecisionService(models, AP_0_1)

    if s.llm == "anthropic":
        llm = FallbackLanguageModel([AnthropicLanguageModel(s.anthropic_api_key or "", s.llm_model), ScriptedLanguageModel()])
    elif s.llm == "scripted":
        llm = ScriptedLanguageModel()
    else:
        raise ValueError(f"unknown NL_LLM {s.llm!r}")

    financial = FinancialUseCases(source, snapshots, bank, profiles, FC_0_1)
    actions = ActionUseCases(snapshots, actions_repo, bank, audit_log, signer, clock, ids, PP_0_1)
    profile_uc = ProfileUseCases(profiles, decisions, conversations, FC_0_1.version)
    audit_uc = AuditUseCases(audit_log)
    registry = build_registry(
        financial, actions, profile_uc, audit_uc, load_tool_definitions(s.resolved_contracts_dir), audit_log, clock, ids, PP_0_1.version
    )
    chat = ChatUseCase(decisions, llm, registry, financial, audit_log, conversations, clock, ids, AP_0_1)

    services = ApplicationServices(
        financial=financial,
        actions=actions,
        profiles=profile_uc,
        audit=audit_uc,
        chat=chat,
        registry=registry,
        default_user=s.persona,
        mode=s.mode,
        language_model=llm.name,
        decision_chain=decisions.chain,
    )
    return services, Adapters(clock, bank, actions_repo, audit_log, source)


def build_services(settings: Settings | None = None) -> ApplicationServices:
    return build(settings)[0]
