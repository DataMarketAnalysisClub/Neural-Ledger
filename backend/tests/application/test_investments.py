"""Linking, syncing and unlinking an investment account, and the read the agent uses (ADR-044)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from neural_ledger.adapters.outbound.investments.fixture import FixtureInvestmentProvider
from neural_ledger.adapters.outbound.persistence.memory import InMemoryAuditLog, InMemoryInvestmentStore
from neural_ledger.adapters.outbound.system.clock import FixedClock
from neural_ledger.adapters.outbound.system.ids import SequentialIds
from neural_ledger.application.ports import InvestmentAccessRejected, InvestmentProviderUnavailable
from neural_ledger.application.use_cases.investments import CONSENT_VERSION, InvestmentUseCases, LinkStatus
from neural_ledger.domain.audit.events import AuditKind
from neural_ledger.domain.investments.model import ReportedGoal
from neural_ledger.domain.shared.envelope import Status
from neural_ledger.domain.shared.serialization import to_primitive
from tests.conftest import make_settings

AT = datetime(2026, 10, 29, 15, 0, tzinfo=UTC)
USER = "usr_inv"
SESSION = "sess_inv"
EMAIL = "Ana.Inversora@Example.invalid"
PASSWORD = "synthetic-password-for-tests"
GOALS = (ReportedGoal("24", "Mi Casita", Decimal("1500000.4"), Decimal("1400000")), ReportedGoal("25", "Viaje", Decimal("300000")))


class FakeProvider:
    """Programmable: what authenticate and goals answer or raise, and every call they received."""

    name = "fake"
    provider = "fintual"
    synthetic = False

    def __init__(self, *, sign_in: object = "tok-1", goals: object = GOALS) -> None:
        self.sign_in, self.answer, self.calls = sign_in, goals, []

    def authenticate(self, email: str, password: str) -> str:
        self.calls.append(("authenticate", email))
        if isinstance(self.sign_in, BaseException):
            raise self.sign_in
        return self.sign_in

    def goals(self, email: str, token: str) -> tuple[ReportedGoal, ...]:
        self.calls.append(("goals", token))
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer


def _system(provider=None):
    audit = InMemoryAuditLog()
    clock = FixedClock(AT)
    store = InMemoryInvestmentStore(audit)
    provider = provider or FakeProvider()
    return InvestmentUseCases(provider, store, clock, SequentialIds()), provider, store, audit, clock


def _events(audit) -> list:
    return [e.draft for e in audit.events()]


def test_link_stores_the_token_masks_the_email_and_audits_without_secrets():
    investments, provider, store, audit, _ = _system()
    outcome = investments.link(USER, SESSION, EMAIL, PASSWORD, consent=True)
    assert outcome.status is LinkStatus.LINKED
    view = to_primitive(outcome.link)
    assert view == {
        "provider": "fintual", "email": "a***@example.invalid", "linked_at": AT.isoformat(), "synced_at": AT.isoformat(),
        "goals": 2, "synthetic": False, "relink_required": False,
    }
    link = store.link(USER)
    assert (link.email, link.token, link.adapter) == ("ana.inversora@example.invalid", "tok-1", "fake")  # the email normalized once
    assert provider.calls == [("authenticate", "ana.inversora@example.invalid"), ("goals", "tok-1")]
    (event,) = _events(audit)
    assert event.kind is AuditKind.INVESTMENTS_LINKED and event.session_id == SESSION
    assert event.detail == f"provider=fintual;adapter=fake;goals=2;consent={CONSENT_VERSION};synthetic=no;relink=no"
    record = str(event)
    assert "ana" not in record.lower() and "tok-1" not in record and PASSWORD not in record and "1500000" not in record


@pytest.mark.parametrize(
    "email, password, consent, field",
    [
        (EMAIL, PASSWORD, False, "consent"),
        ("not-an-email", PASSWORD, True, "email"),
        (None, PASSWORD, True, "email"),
        (EMAIL, "", True, "password"),
        (EMAIL, "x" * 257, True, "password"),
        (EMAIL, None, True, "password"),
    ],
)
def test_invalid_input_never_reaches_the_provider(email, password, consent, field):
    investments, provider, store, audit, _ = _system()
    outcome = investments.link(USER, SESSION, email, password, consent=consent)
    assert (outcome.status, outcome.field) == (LinkStatus.INVALID_INPUT, field)
    assert provider.calls == [] and store.link(USER) is None and _events(audit) == []
    assert PASSWORD not in (outcome.message or "")


@pytest.mark.parametrize(
    "provider, status",
    [
        (FakeProvider(sign_in=InvestmentAccessRejected("refused")), LinkStatus.ACCESS_REJECTED),
        (FakeProvider(sign_in=InvestmentProviderUnavailable("down")), LinkStatus.PROVIDER_UNAVAILABLE),
        (FakeProvider(goals=InvestmentProviderUnavailable("down")), LinkStatus.PROVIDER_UNAVAILABLE),
        # Signed in, then the goals were refused (Fintual, live, 2026-10-19): the password was right, so it is never blamed.
        (FakeProvider(goals=InvestmentAccessRejected("goals refused")), LinkStatus.READ_REFUSED),
        (FakeProvider(goals=(ReportedGoal("1", "x", Decimal("-5")),)), LinkStatus.PROVIDER_UNAVAILABLE),  # outside its contract
    ],
)
def test_a_failed_link_stores_nothing(provider, status):
    investments, _, store, audit, _ = _system(provider)
    assert investments.link(USER, SESSION, EMAIL, PASSWORD, consent=True).status is status
    assert store.link(USER) is None and store.latest(USER) is None and _events(audit) == []


def test_sync_reads_again_and_a_refused_token_asks_for_a_relink():
    investments, provider, store, audit, clock = _system()
    investments.link(USER, SESSION, EMAIL, PASSWORD, consent=True)
    clock.advance(hours=1)
    provider.answer = (ReportedGoal("24", "Mi Casita", Decimal("1600000")),)
    synced = investments.sync(USER, SESSION)
    assert synced.status is LinkStatus.SYNCED and synced.link.goals == 1
    assert store.latest(USER).total_value == 1_600_000
    assert [e.kind for e in _events(audit)] == [AuditKind.INVESTMENTS_LINKED, AuditKind.INVESTMENTS_SYNCED]

    provider.answer = InvestmentAccessRejected("expired")
    expired = investments.sync(USER, SESSION)
    assert expired.status is LinkStatus.RELINK_REQUIRED and expired.link.relink_required
    assert store.link(USER).expired and store.latest(USER).total_value == 1_600_000  # what was synced stays readable
    calls = len(provider.calls)
    assert investments.sync(USER, SESSION).status is LinkStatus.RELINK_REQUIRED and len(provider.calls) == calls  # no retry
    provider.answer = GOALS
    relinked = investments.link(USER, SESSION, EMAIL, PASSWORD, consent=True)
    assert relinked.status is LinkStatus.LINKED and not store.link(USER).expired
    assert _events(audit)[-1].detail.endswith("relink=yes")


def test_a_token_is_only_sent_back_to_the_adapter_that_issued_it():
    investments, _, store, audit, clock = _system(FixtureInvestmentProvider())
    investments.link(USER, SESSION, EMAIL, PASSWORD, consent=True)
    other = FakeProvider()
    moved = InvestmentUseCases(other, store, clock, SequentialIds())
    assert moved.sync(USER, SESSION).status is LinkStatus.RELINK_REQUIRED and other.calls == []


def test_sync_when_the_provider_is_down_keeps_everything():
    investments, provider, store, audit, _ = _system()
    investments.link(USER, SESSION, EMAIL, PASSWORD, consent=True)
    provider.answer = InvestmentProviderUnavailable("down")
    outcome = investments.sync(USER, SESSION)
    assert outcome.status is LinkStatus.PROVIDER_UNAVAILABLE and outcome.link.goals == 2
    assert not store.link(USER).expired and len(_events(audit)) == 1


def test_unlink_removes_everything_and_the_agent_then_sees_no_account():
    investments, _, store, audit, _ = _system()
    assert investments.unlink(USER, SESSION).status is LinkStatus.NOT_LINKED and _events(audit) == []
    investments.link(USER, SESSION, EMAIL, PASSWORD, consent=True)
    assert investments.unlink(USER, SESSION).status is LinkStatus.UNLINKED
    assert store.link(USER) is None and store.latest(USER) is None
    assert _events(audit)[-1].kind is AuditKind.INVESTMENTS_UNLINKED and _events(audit)[-1].detail == "provider=fintual;adapter=fake"
    overview = investments.overview(USER)
    assert overview.status is Status.INSUFFICIENT_DATA and overview.missing == ("investment_account",)
    assert investments.status(USER).status is LinkStatus.NOT_LINKED and investments.sync(USER, SESSION).status is LinkStatus.NOT_LINKED


def test_the_overview_carries_its_facts_warnings_and_wrapped_names():
    investments, _, _, _, clock = _system()
    investments.link(USER, SESSION, EMAIL, PASSWORD, consent=True)
    overview = investments.overview(USER)
    assert overview.ok and overview.as_of == AT.isoformat() and overview.params_version == "inv-0.1"
    data = to_primitive(overview.data)
    assert data["total_value"] == 1_800_000 and data["total_deposited"] is None and data["total_gain"] is None
    assert data["goals"][0] == {"goal_id": "24", "name": {"untrusted_text": "Mi Casita"}, "value": 1_500_000, "deposited": 1_400_000, "gain": 100_000}
    assert [w.code for w in overview.warnings] == ["INVESTMENTS_AS_REPORTED"]
    clock.advance(hours=25)
    stale = investments.overview(USER)
    assert stale.data.stale and [w.code for w in stale.warnings] == ["INVESTMENTS_AS_REPORTED", "INVESTMENTS_STALE"]


def test_the_agent_answers_from_the_fixture_account_and_passes_the_verifier():
    from neural_ledger.bootstrap.container import build

    services, adapters = build(make_settings())
    services.investments.link(USER, SESSION, EMAIL, PASSWORD, consent=True)
    reply = services.chat.handle("s-inv", USER, "¿Cuánto tengo en Fintual?")
    assert reply.intent == "investments" and reply.tools_called == ("get_investments",)
    assert reply.verification.ok and not reply.fallback_used
    assert "4,511,470 CLP" in reply.text and "411,470 CLP" in reply.text and "Fintual" in reply.text and "synthetic" in reply.text
    unlinked = services.chat.handle("s-inv", "usr_nobody", "How much is in my Fintual account?")
    assert "I don't have your investments yet" in unlinked.text and "Investments section" in unlinked.text and unlinked.verification.ok
