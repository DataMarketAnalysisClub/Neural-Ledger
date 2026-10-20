"""Build the application from settings. The ONLY module that chooses concrete adapters."""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass

from ..adapters.outbound.bank.simulated import SimulatedSandboxBank
from ..adapters.outbound.classifier.jev import JevTransactionClassifier
from ..adapters.outbound.classifier.sklearn_text import SklearnTextClassifier, naive_bayes
from ..adapters.outbound.connections.fintoc import FintocBankFeed
from ..adapters.outbound.connections.fixture import FixtureBankFeed, FixtureMcpClient
from ..adapters.outbound.connections.mcp_http import HttpMcpClient
from ..adapters.outbound.decision.jev import OPENROUTER_BASE_URL, JevDecisionModel
from ..adapters.outbound.decision.rules import RulesDecisionModel
from ..adapters.outbound.email.domains import DisposableEmailBlocklist, DnsEmailDomainCheck
from ..adapters.outbound.fixtures.ledger_source import LedgerModelSource
from ..adapters.outbound.fixtures.persona_source import PersonaFixtureSource
from ..adapters.outbound.knowledge.corpus_loader import load_cards
from ..adapters.outbound.knowledge.lexical import LexicalKnowledgeBase
from ..adapters.outbound.llm.anthropic import AnthropicLanguageModel
from ..adapters.outbound.llm.openrouter import OpenRouterLanguageModel
from ..adapters.outbound.llm.scripted import ScriptedLanguageModel
from ..adapters.outbound.persistence.field_cipher import FieldCipher
from ..adapters.outbound.persistence.memory import (
    InMemoryAccountErasure,
    InMemoryAccountWrites,
    InMemoryActionRepository,
    InMemoryAuditLog,
    InMemoryConnectionStore,
    InMemoryConversationStore,
    InMemoryReceiptStore,
    InMemorySavingsRuleStore,
    InMemorySessionStore,
    InMemorySnapshotStore,
    InMemoryStatementStore,
    InMemoryTransactionStore,
    InMemoryTransactionWrites,
    InMemoryUserAccountStore,
    InMemoryUserProfileStore,
)
from ..adapters.outbound.persistence.overlay import PersonaOverlayProfileStore
from ..adapters.outbound.persistence.sqlite import (
    SqliteAccountErasure,
    SqliteAccountWrites,
    SqliteActionRepository,
    SqliteAuditLog,
    SqliteConnectionStore,
    SqliteDatabase,
    SqliteReceiptStore,
    SqliteSavingsRuleStore,
    SqliteSessionStore,
    SqliteStatementStore,
    SqliteTransactionStore,
    SqliteTransactionWrites,
    SqliteUserAccountStore,
    SqliteUserProfileStore,
    verify_data_key,
)
from ..adapters.outbound.persistence.sqlite_migration import migrate
from ..adapters.outbound.privacy.azure_language import AzureLanguageDetector
from ..adapters.outbound.privacy.null import NullDetector
from ..adapters.outbound.receipts.reader import ReceiptFileReader
from ..adapters.outbound.statements.reader import StatementFileReader
from ..adapters.outbound.system.clock import FixedClock, SystemClock
from ..adapters.outbound.system.ids import SequentialIds, UuidIds
from ..adapters.outbound.system.password import ScryptHasher
from ..adapters.outbound.system.signer import HmacSigner
from ..adapters.outbound.system.tokens import SecretsTokens
from ..application.catalog import build_registry
from ..application.facade import ApplicationServices, AuthConfig
from ..application.ports import (
    BankFeed,
    Clock,
    EmailDomainCheck,
    KnowledgeBase,
    McpClient,
    PersonalDataDetector,
    TransactionClassifier,
)
from ..application.services.classifier_fallback import FallbackClassifier
from ..application.services.decisions import DecisionService
from ..application.services.knowledge_fallback import FallbackKnowledgeBase
from ..application.services.knowledge_threshold import ThresholdKnowledgeBase
from ..application.services.llm_fallback import FallbackLanguageModel
from ..application.services.posting import LedgerPosting
from ..application.services.redaction import StatementRedactor
from ..application.services.statement_model import FirstFoundModelSource, StatementModelSource
from ..application.use_cases.accounts import DEMO_PERSONAS, AccountUseCases
from ..application.use_cases.actions import ActionUseCases
from ..application.use_cases.audit import AuditUseCases
from ..application.use_cases.chat import ChatUseCase
from ..application.use_cases.connections import ConnectionUseCases
from ..application.use_cases.documents import DocumentUseCases
from ..application.use_cases.education import EducationUseCases
from ..application.use_cases.financial import FinancialUseCases
from ..application.use_cases.ledger import LedgerUseCases
from ..application.use_cases.profile import ProfileEditing, ProfileUseCases
from ..application.use_cases.statements import StatementUseCases
from ..domain.agent.policy import AP_0_1
from ..domain.education.concepts import ConceptCard
from ..domain.finance.params import FC_0_1
from ..domain.permissions.policy import PP_0_1
from . import data_key
from .config import DEV_SECRET, Settings
from .contracts import load_tool_definitions

logger = logging.getLogger(__name__)

# Spending classifiers for imported statements, by NL_CLASSIFIER (comma-separated, tried in order: jev,naive_bayes).
# To change the method, add an entry (any TransactionClassifier) and select it; to change the estimator, pass
# another pipeline factory. jev sends each distinct line text, already redacted, to Jev (ADR-032).
CLASSIFIERS: dict[str, Callable[[Settings], TransactionClassifier]] = {
    "naive_bayes": lambda s: SklearnTextClassifier(naive_bayes, method="naive_bayes"),
    "jev": lambda s: JevTransactionClassifier(_jev(s)),
}



def _chroma(s: Settings, cards: tuple[ConceptCard, ...]) -> KnowledgeBase:
    from ..adapters.outbound.knowledge.chroma import ChromaKnowledgeBase  # imports nothing optional; chromadb loads at first search

    return ChromaKnowledgeBase(cards, s.kb_dir, s.kb_embedding_model, url=s.kb_url)


# Concept-card indexes for explanations, by NL_KNOWLEDGE_BASE (comma-separated, tried in order: chroma,lexical), ADR-040.
# lexical is BM25 in the standard library (offline, the default); chroma needs the `rag` extra and downloads the
# embedding model into NL_KB_DIR at first use. To add a method, implement KnowledgeBase and add an entry here.
KNOWLEDGE_BASES: dict[str, Callable[[Settings, tuple[ConceptCard, ...]], KnowledgeBase]] = {
    "lexical": lambda s, cards: LexicalKnowledgeBase(cards),
    "chroma": _chroma,
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
    knowledge_base: KnowledgeBase | None = None


# Relevance floor per index, by NL_KNOWLEDGE_BASE name (ADR-040): scores are on different scales, so each index in the
# chain is wrapped with its own floor (ThresholdKnowledgeBase) before the fallback. From the WP2 eval on the 70 cards:
# lexical answerable min 0.573 / off-topic max 0.379; chroma answerable min 0.425 / off-topic max 0.23.
KB_MIN_SCORES: dict[str, float] = {"lexical": 0.45, "chroma": 0.30}


# NL_EMAIL_CHECKS, applied in order at sign-up: disposable (offline blocklist) and dns (the domain receives mail).
EMAIL_CHECKS: dict[str, Callable[[], EmailDomainCheck]] = {"disposable": DisposableEmailBlocklist, "dns": DnsEmailDomainCheck}


def _email_checks(names: tuple[str, ...]) -> list[EmailDomainCheck]:
    unknown = [name for name in names if name not in EMAIL_CHECKS]
    if unknown:
        raise ValueError(f"unknown email check {unknown[0]!r} in NL_EMAIL_CHECKS (use {', '.join(EMAIL_CHECKS)} or none)")
    return [EMAIL_CHECKS[name]() for name in names]


def _jev(s: Settings) -> JevDecisionModel:
    """Jev through OpenRouter when its key is set (D-02); a TypeSafe key is only the direct path to the same API."""
    if s.openrouter_api_key or not s.typesafe_api_key:
        return JevDecisionModel(s.openrouter_api_key, s.jev_model, base_url=OPENROUTER_BASE_URL)
    return JevDecisionModel(s.typesafe_api_key, s.jev_model)


def _data_cipher(s: Settings) -> FieldCipher:
    """G11: the key that seals SQLite payloads, never stored in the database (bootstrap/data_key.py).

    A Docker secret or NL_DATA_KEY_FILE first, then NL_DATA_KEY. Live mode and NL_DEPLOYMENT=deployed need one.
    Local offline runs (tests, docker compose, the demo) without it get a random key in <db>.key, created once,
    with a loud warning: the database alone, or a copy of it, reads nothing, but a copy of the volume does."""
    key = data_key.resolve(s)
    data_key.check(s, key)
    if key is not None:
        return FieldCipher.from_hex(key.hex)
    if s.mode == "live":
        raise ValueError("live mode with SQLite needs NL_DATA_KEY (64 hex characters) to encrypt statements at rest")
    if s.sqlite_path == ":memory:":
        return FieldCipher(secrets.token_bytes(32))  # the data dies with the process, and so does its key
    path = data_key.legacy_key_file(s.sqlite_path)
    data_key.warn_key_file_fallback(path)
    return FieldCipher.from_key_file(path)


AUTH_MODES = ("demo", "accounts")
COOKIE_SECURE = ("auto", "true", "false")


def _auth_config(s: Settings) -> AuthConfig:
    if s.auth not in AUTH_MODES:
        raise ValueError(f"unknown NL_AUTH {s.auth!r} (demo | accounts)")
    if s.cookie_secure not in COOKIE_SECURE:
        raise ValueError(f"unknown NL_COOKIE_SECURE {s.cookie_secure!r} (auto | true | false)")
    origins = tuple(s.app_origins)
    if s.auth == "accounts" and (not origins or any(o in ("*", "null") or "://" not in o for o in origins)):
        raise ValueError("NL_APP_ORIGINS must list exact origins (scheme://host[:port]) in accounts mode")
    demo_personas = DEMO_PERSONAS if s.auth == "accounts" and s.demo_personas else ()
    return AuthConfig(s.auth, origins, s.cookie_secure, demo_personas)


def _connectors(s: Settings, clock: Clock) -> tuple[McpClient, BankFeed | None]:
    """ADR-047: synthetic servers by default; live ones reach the network and, for the bank, need Fintoc's keys."""
    if s.connectors not in ("fixture", "live"):
        raise ValueError(f"unknown NL_CONNECTORS {s.connectors!r} (fixture | live)")
    if s.mcp_allow_private and s.deployment == "deployed":
        raise ValueError("NL_MCP_ALLOW_PRIVATE is for local development only and is refused with NL_DEPLOYMENT=deployed")
    if s.connectors == "fixture":
        return FixtureMcpClient(), FixtureBankFeed(clock)
    bank = FintocBankFeed(s.fintoc_secret_key, s.fintoc_public_key) if s.fintoc_secret_key and s.fintoc_public_key else None
    return HttpMcpClient(allow_private=s.mcp_allow_private), bank


def build(settings: Settings | None = None) -> tuple[ApplicationServices, Adapters]:
    s = settings or Settings.from_env()
    if s.deployment not in data_key.DEPLOYMENTS:
        raise ValueError(f"unknown NL_DEPLOYMENT {s.deployment!r} (local | deployed)")
    if s.hmac_secret == DEV_SECRET and (s.mode == "live" or s.deployment == "deployed"):
        raise ValueError(
            f"{'live mode' if s.mode == 'live' else 'NL_DEPLOYMENT=deployed'} refuses the development default for "
            'NL_HMAC_SECRET; set a real one, e.g. python -c "import secrets; print(secrets.token_hex(32))"'
        )

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

    auth = _auth_config(s)
    db: SqliteDatabase | None = None
    if s.persistence == "sqlite":
        cipher = _data_cipher(s)  # before the database is opened: a refused key leaves no file behind
        db = SqliteDatabase(s.sqlite_path)
        if db.needs_migration:
            migrate(db, cipher)  # an older file: the current schema, everything sealed; it opens every value, so it checks the key too
        else:
            verify_data_key(db, cipher)
        actions_repo: InMemoryActionRepository | SqliteActionRepository = SqliteActionRepository(db, cipher)
        audit_log: InMemoryAuditLog | SqliteAuditLog = SqliteAuditLog(db, cipher)
        rule_store: InMemorySavingsRuleStore | SqliteSavingsRuleStore = SqliteSavingsRuleStore(db, cipher)
        statement_store: InMemoryStatementStore | SqliteStatementStore = SqliteStatementStore(db, cipher)
        receipt_store: InMemoryReceiptStore | SqliteReceiptStore = SqliteReceiptStore(db, cipher)
        connection_store: InMemoryConnectionStore | SqliteConnectionStore = SqliteConnectionStore(db, cipher)
        transaction_store: InMemoryTransactionStore | SqliteTransactionStore = SqliteTransactionStore(db, cipher)
        transaction_writes: InMemoryTransactionWrites | SqliteTransactionWrites = SqliteTransactionWrites(db, cipher)
        writable_profiles: InMemoryUserProfileStore | SqliteUserProfileStore = SqliteUserProfileStore(db, cipher)
    else:
        actions_repo, audit_log, rule_store = InMemoryActionRepository(), InMemoryAuditLog(), InMemorySavingsRuleStore()
        statement_store, transaction_store = InMemoryStatementStore(), InMemoryTransactionStore()
        receipt_store = InMemoryReceiptStore()
        connection_store = InMemoryConnectionStore()
        transaction_writes = InMemoryTransactionWrites(transaction_store, audit_log)
        writable_profiles = InMemoryUserProfileStore()

    snapshots = InMemorySnapshotStore()
    conversations = InMemoryConversationStore()
    bank = SimulatedSandboxBank(rule_store)
    # Personas are read-only fixtures in front of the writable store (account profiles), in both persistence modes.
    profiles = PersonaOverlayProfileStore([personas.profile(name) for name in personas.user_ids()], writable_profiles)

    accounts: AccountUseCases | None = None
    profile_editing: ProfileEditing | None = None
    if auth.accounts:
        # Exactly one writes object over the SAME account, session, profile and audit objects the rest of the app uses,
        # built before any request: InMemoryAccountWrites re-points their locks, and SQLite shares one database.
        if db is not None:
            account_store: InMemoryUserAccountStore | SqliteUserAccountStore = SqliteUserAccountStore(db, cipher)
            session_store: InMemorySessionStore | SqliteSessionStore = SqliteSessionStore(db)
            writes: InMemoryAccountWrites | SqliteAccountWrites = SqliteAccountWrites(db, cipher)
            erasure: InMemoryAccountErasure | SqliteAccountErasure = SqliteAccountErasure(db, cipher)
        else:
            account_store, session_store = InMemoryUserAccountStore(), InMemorySessionStore()
            writes = InMemoryAccountWrites(account_store, session_store, profiles, audit_log)
            erasure = InMemoryAccountErasure(
                account_store, session_store, profiles, audit_log, statement_store, transaction_store, rule_store, actions_repo,
                receipt_store, connection_store,
            )
        accounts = AccountUseCases(
            account_store, session_store, writes, ScryptHasher(), SecretsTokens(), clock, ids,
            demo_personas=frozenset(auth.demo_personas), transactions=transaction_store,
            erasure=erasure, forget=(conversations, snapshots),  # in-memory state the erasure transaction cannot reach
            email_checks=_email_checks(s.email_checks),
        )
        profile_editing = ProfileEditing(profiles, writes, clock, ids, FC_0_1.version)

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
        # Deprecated, not refused: ADR-027 (OpenRouter as the only live provider) is still Proposed.
        logger.warning("NL_LLM=anthropic is deprecated (ADR-027): use NL_LLM=openrouter; this provider will be removed")
        llm = FallbackLanguageModel([AnthropicLanguageModel(s.anthropic_api_key or "", s.resolved_llm_model), ScriptedLanguageModel()])
    elif s.llm == "openrouter":
        llm = FallbackLanguageModel([OpenRouterLanguageModel(s.openrouter_api_key or "", s.resolved_llm_model), ScriptedLanguageModel()])
    elif s.llm == "scripted":
        llm = ScriptedLanguageModel()
    else:
        raise ValueError(f"unknown NL_LLM {s.llm!r}")

    # Personas keep their fixtures; every other user gets the model of their own statements (ADR-029).
    accounts_source = StatementModelSource(statement_store, transaction_store, FC_0_1)
    financial = FinancialUseCases(FirstFoundModelSource((source, accounts_source)), snapshots, bank, profiles, FC_0_1)
    actions = ActionUseCases(snapshots, actions_repo, bank, audit_log, signer, clock, ids, PP_0_1, plan_origin=financial.plan_origin)
    profile_uc = ProfileUseCases(profiles, decisions, conversations, FC_0_1.version)
    audit_uc = AuditUseCases(audit_log)
    unknown = [name for name in s.classifiers if name not in CLASSIFIERS]
    if unknown:
        raise ValueError(f"unknown NL_CLASSIFIER {', '.join(unknown)!r} (known: {', '.join(CLASSIFIERS)})")
    chain = [CLASSIFIERS[name](s) for name in s.classifiers]
    classifier = chain[0] if len(chain) == 1 else FallbackClassifier(chain)
    posting = LedgerPosting(classifier, transaction_store)
    unknown = [name for name in s.knowledge_bases if name not in KNOWLEDGE_BASES]
    if unknown:
        raise ValueError(f"unknown NL_KNOWLEDGE_BASE {', '.join(unknown)!r} (known: {', '.join(KNOWLEDGE_BASES)})")
    cards = load_cards()
    kb_chain = [ThresholdKnowledgeBase(KNOWLEDGE_BASES[name](s, cards), KB_MIN_SCORES[name]) for name in s.knowledge_bases]
    knowledge_base = kb_chain[0] if len(kb_chain) == 1 else FallbackKnowledgeBase(kb_chain)
    if s.pii_detector not in DETECTORS:
        raise ValueError(f"unknown NL_PII_DETECTOR {s.pii_detector!r} (known: {', '.join(DETECTORS)})")
    redactor = StatementRedactor(DETECTORS[s.pii_detector](s))  # personal data is removed at import, before anything is stored
    statements = StatementUseCases(StatementFileReader(model_dir=s.ocr_model_dir), redactor, statement_store, posting, audit_log, clock, ids)
    ledger = LedgerUseCases(transaction_store, transaction_writes, clock, ids)
    # Documents dropped on the copilot (ADR-039): routed by the domain rules, then by the decision chain (Jev when set).
    documents = DocumentUseCases(
        ReceiptFileReader(model_dir=s.ocr_model_dir), redactor, statements, receipt_store, transaction_store, classifier, models,
        financial, audit_log, clock, ids, snapshots,
    )
    # The floor is applied per index (KB_MIN_SCORES, ThresholdKnowledgeBase) when the chain is built, so 0 here.
    education = EducationUseCases(knowledge_base, 0.0, profiles)
    mcp, bank_feed = _connectors(s, clock)
    connections = ConnectionUseCases(connection_store, mcp, bank_feed, statements, audit_log, clock, ids, s.connectors_mode)
    registry = build_registry(
        financial, actions, profile_uc, audit_uc, documents, education, load_tool_definitions(s.resolved_contracts_dir), audit_log, clock, ids,
        PP_0_1.version, connections,
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
        classifier=classifier.name,
        clock=clock,
        auth=auth,
        accounts=accounts,
        profile_editing=profile_editing,
        persistence=s.persistence,
        documents=documents,
        connections=connections,
    )
    return services, Adapters(clock, bank, actions_repo, audit_log, source, knowledge_base)


def build_services(settings: Settings | None = None) -> ApplicationServices:
    return build(settings)[0]
