import json
from datetime import UTC, datetime

from neural_ledger.adapters.outbound.persistence.memory import (
    InMemoryAccountWrites,
    InMemoryAuditLog,
    InMemorySessionStore,
    InMemoryUserAccountStore,
    InMemoryUserProfileStore,
)
from neural_ledger.adapters.outbound.system.clock import FixedClock
from neural_ledger.adapters.outbound.system.ids import SequentialIds
from neural_ledger.adapters.outbound.system.password import ScryptHasher
from neural_ledger.adapters.outbound.system.tokens import SecretsTokens
from neural_ledger.application.use_cases.accounts import AccountUseCases
from neural_ledger.domain.audit.events import AuditKind, verify_chain

from ..conftest import CONTRACTS


def test_audit_kinds_match_the_schema_enum_exactly():
    schema = json.loads((CONTRACTS / "audit/audit_event.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["kind"]["enum"] == [kind.value for kind in AuditKind]


def test_account_flow_audit_events_match_the_contract():
    from .test_contracts import validate  # skips when jsonschema is not installed

    audit = InMemoryAuditLog()
    account_store, session_store, profile_store = InMemoryUserAccountStore(), InMemorySessionStore(), InMemoryUserProfileStore()
    accounts = AccountUseCases(
        account_store, session_store, InMemoryAccountWrites(account_store, session_store, profile_store, audit),
        ScryptHasher(), SecretsTokens(), FixedClock(datetime(2026, 10, 29, 9, tzinfo=UTC)), SequentialIds(),
    )
    issued = accounts.signup("ana@example.com", "correct horse battery", "Ana").session
    signin = accounts.signin("ana@example.com", "correct horse battery").session
    assert accounts.set_sample_data(issued.user_id, issued.session_ref, True).ok
    assert accounts.signout(signin.token)
    events = audit.events()
    assert {e.draft.kind for e in events} == {
        AuditKind.USER_REGISTERED, AuditKind.SESSION_STARTED, AuditKind.PROFILE_UPDATED, AuditKind.SESSION_ENDED,
    }
    assert verify_chain(events).ok
    for event in events:
        validate(event.to_record(), "audit/audit_event.schema.json")
