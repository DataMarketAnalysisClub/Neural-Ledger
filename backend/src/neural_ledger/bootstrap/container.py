"""Build the application from settings. The ONLY module that chooses concrete adapters."""

from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass

from ..adapters.outbound.bank.simulated import SimulatedSandboxBank
from ..adapters.outbound.classifier.sklearn_text import SklearnTextClassifier, naive_bayes
from ..adapters.outbound.decision.jev import OPENROUTER_BASE_URL, JevDecisionModel
from ..adapters.outbound.decision.rules import RulesDecisionModel
from ..adapters.outbound.fixtures.ledger_source import LedgerModelSource
from ..adapters.outbound.fixtures.persona_source import PersonaFixtureSource
from ..adapters.outbound.llm.anthropic import AnthropicLanguageModel
from ..adapters.outbound.llm.openrouter import OpenRouterLanguageModel
from ..adapters.outbound.llm.scripted import ScriptedLanguageModel
from ..adapters.outbound.persistence.memory import (
    InMemoryActionRepository,
    InMemoryAuditLog,
    InMemoryConversationStore,
    InMemorySavingsRuleStore,
    InMemorySnapshotStore,
    InMemoryStatementStore,
    InMemoryTransactionStore,
    InMemoryUserProfileStore,
)
from ..adapters.outbound.persistence.sqlite import (
    SqliteActionRepository,
    SqliteAuditLog,
    SqliteDatabase,
    SqliteSavingsRuleStore,
    SqliteStatementStore,
    SqliteTransactionStore,
)
from ..adapters.outbound.privacy.azure_language import AzureLanguageDetector
from ..adapters.outbound.privacy.null import NullDetector
from ..adapters.outbound.statements.reader import StatementFileReader
from ..adapters.outbound.system.clock import FixedClock, SystemClock
from ..adapters.outbound.system.ids import SequentialIds, UuidIds
from ..adapters.outbound.system.signer import HmacSigner
from ..application.catalog import build_registry
from ..application.facade import ApplicationServices
from ..application.ports import PersonalDataDetector, TransactionClassifier
from ..application.services.decisions import DecisionService
from ..application.services.llm_fallback import FallbackLanguageModel
from ..application.services.posting import LedgerPosting
from ..application.services.redaction import StatementRedactor
from ..application.use_cases.actions import ActionUseCases
from ..application.use_cases.audit import AuditUseCases
from ..application.use_cases.chat import ChatUseCase
from ..application.use_cases.financial import FinancialUseCases
from ..application.use_cases.ledger import LedgerUseCases
from ..application.use_cases.profile import ProfileUseCases
from ..application.use_cases.statements import StatementUseCases
from ..domain.agent.policy import AP_0_1
from ..domain.finance.params import FC_0_1
from ..domain.permissions.policy import PP_0_1
from .config import DEV_SECRET, Settings
from .contracts import load_tool_definitions

# Spending classifiers for imported statements, by NL_CLASSIFIER. To change the method, add an entry
# (any TransactionClassifier) and select it; to change the estimator, pass another pipeline factory.
CLASSIFIERS: dict[str, Callable[[], TransactionClassifier]] = {
    "naive_bayes": lambda: SklearnTextClassifier(naive_bayes, method="naive_bayes"),
}

# Personal-data detectors, by NL_PII_DETECTOR: a second layer after the domain rules on every imported statement
# (ADR-028). To add one, implement PersonalDataDetector in adapters/outbound/privacy/ and add an entry here.
DETECTORS: dict[str, Callable[[Settings], PersonalDataDetector]] = {
    "none": lambda s: NullDetector(),  # rules only: CI, docker compose, the recorded demo
    "azure": lambda s: AzureLanguageDetector(s.azure_language_endpoint or "", s.azure_language_api_key or ""),
}


@dataclass
class Adapters:
    """Concrete adapters, exposed for tests (e.g. to inject a bank failure or advance the clock)."""

    clock: FixedClock | SystemClock
    bank: SimulatedSandboxBank
    actions_repo: InMemoryActionRepository | SqliteActionRepository
    audit_log: InMemoryAuditLog | SqliteAuditLog
    source: PersonaFixtureSource | LedgerModelSource


def _jev(s: Settings) -> JevDecisionModel:
    """Jev through OpenRouter when its key is set (D-02); a TypeSafe key is only the direct path to the same API."""
    if s.openrouter_api_key or not s.typesafe_api_key:
        return JevDecisionModel(s.openrouter_api_key, s.jev_model, base_url=OPENROUTER_BASE_URL)
    return JevDecisionModel(s.typesafe_api_key, s.jev_model)


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
        statement_store: InMemoryStatementStore | SqliteStatementStore = SqliteStatementStore(db)
        transaction_store: InMemoryTransactionStore | SqliteTransactionStore = SqliteTransactionStore(db)
    else:
        actions_repo, audit_log, rule_store = InMemoryActionRepository(), InMemoryAuditLog(), InMemorySavingsRuleStore()
        statement_store, transaction_store = InMemoryStatementStore(), InMemoryTransactionStore()

    snapshots = InMemorySnapshotStore()
    conversations = InMemoryConversationStore()
    bank = SimulatedSandboxBank(rule_store)
    profiles = InMemoryUserProfileStore([personas.profile(name) for name in personas.user_ids()])

    models = []
    for name in s.decision_chain:
        if name == "rules":
            models.append(RulesDecisionModel())
        elif name == "jev":
            models.append(_jev(s))
        else:
            raise ValueError(f"unknown decision model {name!r} in NL_DECISION_CHAIN")
    decisions = DecisionService(models, AP_0_1)

    if s.llm == "anthropic":
        llm = FallbackLanguageModel([AnthropicLanguageModel(s.anthropic_api_key or "", s.resolved_llm_model), ScriptedLanguageModel()])
    elif s.llm == "openrouter":
        llm = FallbackLanguageModel([OpenRouterLanguageModel(s.openrouter_api_key or "", s.resolved_llm_model), ScriptedLanguageModel()])
    elif s.llm == "scripted":
        llm = ScriptedLanguageModel()
    else:
        raise ValueError(f"unknown NL_LLM {s.llm!r}")

    financial = FinancialUseCases(source, snapshots, bank, profiles, FC_0_1)
    actions = ActionUseCases(snapshots, actions_repo, bank, audit_log, signer, clock, ids, PP_0_1)
    profile_uc = ProfileUseCases(profiles, decisions, conversations, FC_0_1.version)
    audit_uc = AuditUseCases(audit_log)
    if s.classifier not in CLASSIFIERS:
        raise ValueError(f"unknown NL_CLASSIFIER {s.classifier!r} (known: {', '.join(CLASSIFIERS)})")
    posting = LedgerPosting(CLASSIFIERS[s.classifier](), transaction_store)
    if s.pii_detector not in DETECTORS:
        raise ValueError(f"unknown NL_PII_DETECTOR {s.pii_detector!r} (known: {', '.join(DETECTORS)})")
    redactor = StatementRedactor(DETECTORS[s.pii_detector](s))  # personal data is removed at import, before anything is stored
    statements = StatementUseCases(StatementFileReader(model_dir=s.ocr_model_dir), redactor, statement_store, posting, audit_log, clock, ids)
    ledger = LedgerUseCases(transaction_store)
    registry = build_registry(
        financial, actions, profile_uc, audit_uc, load_tool_definitions(s.resolved_contracts_dir), audit_log, clock, ids, PP_0_1.version
    )
    chat = ChatUseCase(decisions, llm, registry, financial, audit_log, conversations, clock, ids, AP_0_1)

    services = ApplicationServices(
        financial=financial,
        actions=actions,
        profiles=profile_uc,
        audit=audit_uc,
        statements=statements,
        ledger=ledger,
        chat=chat,
        registry=registry,
        default_user=s.persona,
        mode=s.mode,
        language_model=llm.name,
        decision_chain=decisions.chain,
        pii_detector=redactor.detector,
        clock=clock,
        persistence=s.persistence,
    )
    return services, Adapters(clock, bank, actions_repo, audit_log, source)


def build_services(settings: Settings | None = None) -> ApplicationServices:
    return build(settings)[0]
