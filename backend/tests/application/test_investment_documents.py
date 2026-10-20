"""ADR-044, statement import: a Fintual statement and transactions certificate dropped in the app become what the
agent knows about the user's investments. Production wiring, offline, clock on 2026-10-19; the documents are the
synthetic ones of tests/investment_samples.py, whose figures are worked out by hand there."""

from __future__ import annotations

import pytest

pytest.importorskip("pymupdf")
pytest.importorskip("pdfplumber")

from neural_ledger.application.services import narration  # noqa: E402
from neural_ledger.domain.audit.events import AuditKind  # noqa: E402
from neural_ledger.domain.shared.envelope import Status  # noqa: E402
from neural_ledger.domain.shared.serialization import to_primitive  # noqa: E402
from tests.investment_samples import HOLDER, HOLDER_RUT, HOME, RAINY_DAY, TRIP, holdings_pdf, movement_rows, movements_pdf  # noqa: E402
from tests.receipt_samples import boleta_pdf  # noqa: E402

USER = "usr_docs"
SESSION = "s-inv-docs"
TODAY = "2026-10-19T12:00:00-03:00"


@pytest.fixture
def system():
    from neural_ledger.bootstrap.container import build
    from tests.conftest import make_settings

    return build(make_settings(fixed_now=TODAY))


def _steps(envelope) -> list[tuple[str, str, str | None]]:
    return [(s.key, s.status, s.value) for s in envelope.data.steps]


def _imports(adapters) -> list[str | None]:
    return [e.draft.execution_result for e in adapters.audit_log.events() if e.draft.kind is AuditKind.INVESTMENT_DOCUMENT_IMPORTED]


def _drop_both(services):
    statement = services.documents.ingest(USER, holdings_pdf(), SESSION, investments=True)
    certificate = services.documents.ingest(USER, movements_pdf(), SESSION, investments=True)
    return statement, certificate


def test_both_documents_become_what_the_agent_reads(services, adapters):
    statement, certificate = _drop_both(services)

    assert statement.ok and statement.data.kind == "investment" and statement.data.receipt is None and statement.data.statement is None
    assert _steps(statement) == [
        ("read", "done", "pdf"), ("route", "done", "investment"), ("verify", "done", "verified"),
        ("duplicate", "done", "new"), ("investments", "done", "holdings"),
    ]
    assert ("redact", "done", None) in _steps(certificate) and ("investments", "done", "movements") in _steps(certificate)
    overview = services.investments.overview(USER)
    data = overview.data
    assert (data.source, data.as_of, data.total_value, data.total_deposited, data.total_gain, data.gain_pct) == (
        "statement", "2026-10-14", 422_097, 372_333, 49_764, 13.4,
    )
    assert data.documents_agree is True and [f.fund for f in data.funds] == ["Risky Norris", "Conservative Clooney", "Moderate Pitt"]
    c = data.contributions
    assert (c.contributed, c.withdrawn, c.contributions, c.months, c.active_months, c.monthly_average, c.complete) == (385_333, 13_000, 8, 11, 6, 35_030, True)
    goals = {g.name["untrusted_text"]: (g.value, g.deposited, g.gain) for g in data.goals}
    assert goals == {TRIP: (285_073, 245_000, 40_073), RAINY_DAY: (56_515, 52_333, 4_182), HOME: (80_509, 75_000, 5_509)}
    # What the copilot gets back right away carries the same figures as facts.
    assert {f.key: f.value for f in certificate.facts}["investments.total_gain"] == 49_764
    assert _imports(adapters) == ["VERIFIED", "VERIFIED"]
    routed = [e.draft.detail for e in adapters.audit_log.events() if e.draft.kind is AuditKind.DOCUMENT_ROUTED]
    assert routed and all("kind=investment by=rules" in d for d in routed)


def test_the_copilot_answers_from_the_documents_and_passes_the_verifier(services):
    _drop_both(services)
    reply = services.chat.handle(SESSION, USER, "Acabo de agregar mis documentos de Fintual. ¿Cómo van mis inversiones?")
    assert reply.intent == "investments" and reply.tools_called == ("get_investments",)
    assert reply.verification.ok and not reply.fallback_used
    for figure in ("422,097 CLP", "385,333 CLP", "372,333 CLP", "35,030 CLP", "49,764 CLP", "13.4%", "Fintual"):
        assert figure in reply.text, figure
    assert not any(name in reply.text for name in (TRIP, RAINY_DAY, HOME))  # goal names are never the assistant's words (S30)


def test_the_latest_document_tells_the_copilot_what_changed(services):
    statement, _ = _drop_both(services)
    latest = services.documents.latest_document(USER)
    assert latest.ok and latest.data.kind == "investment" and latest.data.investment.document.kind == "movements"
    text = narration.narrate([("get_latest_document", to_primitive(latest))], "CLP")
    assert "I read your Fintual transactions certificate" in text and "49,764 CLP" in text


def test_a_document_that_does_not_add_up_is_reported_and_nothing_is_kept(services, adapters):
    result = services.documents.ingest(USER, holdings_pdf(total_delta=1_000), SESSION, investments=True)
    assert result.ok
    document = result.data.investment.document
    assert not document.verified and document.issues[0]["code"] == "TOTAL_MISMATCH" and document.imported_at is None
    assert ("verify", "warning", "unverified") in _steps(result) and ("investments", "skipped", "holdings") in _steps(result)
    assert [w.code for w in result.warnings] == ["INVESTMENT_DOCUMENT_UNVERIFIED"] and result.facts == ()
    assert services.investments.overview(USER).status is Status.INSUFFICIENT_DATA
    assert _imports(adapters) == ["UNVERIFIED"]


def test_the_same_document_twice_changes_nothing(services, adapters):
    services.documents.ingest(USER, holdings_pdf(), SESSION, investments=True)
    again = services.documents.ingest(USER, holdings_pdf(), SESSION, investments=True)
    assert again.data.investment.duplicate and ("duplicate", "warning", "duplicate") in _steps(again)
    assert "INVESTMENT_DOCUMENT_DUPLICATE" in {w.code for w in again.warnings}
    assert len(services.investments.overview(USER).data.documents) == 1 and _imports(adapters) == ["VERIFIED", "DUPLICATE"]


def test_a_shared_demo_profile_cannot_import_investments(services, adapters):
    for kind in (None, "investment"):
        refused = services.documents.ingest(USER, holdings_pdf(), SESSION, kind)  # investments=False: what HTTP sends for a persona
        assert refused.status is Status.INVALID_INPUT and refused.field == "kind" and "signed-in account" in refused.message
    assert services.investments.overview(USER).status is Status.INSUFFICIENT_DATA and _imports(adapters) == []


def test_the_user_can_say_where_a_file_goes_but_not_make_a_receipt_an_investment(services):
    assert services.documents.ingest(USER, movements_pdf(), SESSION, "investment", investments=True).ok
    wrong = services.documents.ingest(USER, boleta_pdf(), SESSION, "investment", investments=True)
    assert wrong.status is Status.INVALID_INPUT and wrong.field == "file" and "not a document issued by Fintual" in wrong.message
    unknown = services.documents.ingest(USER, boleta_pdf(), SESSION, "crypto", investments=True)
    assert unknown.status is Status.INVALID_INPUT and unknown.allowed == ("receipt", "statement", "investment")


def test_goal_names_are_redacted_before_they_are_stored(services):
    rows = [row.replace(TRIP, "Ahorro de ana.perez@example.invalid") for row in movement_rows()]
    assert services.documents.ingest(USER, movements_pdf(rows=rows), SESSION, investments=True).ok
    stored = {m.goal for d in services.investments._store.documents(USER) for m in d.movements}
    assert not any("ana.perez@example.invalid" in goal for goal in stored)
    for d in services.investments._store.documents(USER):  # the holder is never read, so never stored
        assert HOLDER not in repr(d) and HOLDER_RUT not in repr(d)


def test_a_statement_alone_has_no_contributions_and_says_why(services):
    services.documents.ingest(USER, holdings_pdf(), SESSION, investments=True)
    overview = services.investments.overview(USER)
    assert overview.data.total_value == 422_097 and overview.data.contributions is None and overview.data.goals == ()
    assert {w.code for w in overview.warnings} == {"INVESTMENTS_FROM_STATEMENT", "INVESTMENTS_NO_HISTORY"}


def test_imported_documents_win_over_a_linked_sandbox_account(services):
    services.investments.link(USER, SESSION, "sandbox@example.invalid", "synthetic-password", consent=True)
    assert services.investments.overview(USER).data.source == "sync"
    services.documents.ingest(USER, holdings_pdf(), SESSION, investments=True)
    assert services.investments.overview(USER).data.source == "statement"


def test_removing_the_documents_forgets_them(services, adapters):
    _drop_both(services)
    assert services.investments.remove_documents(USER, SESSION) == 2
    assert services.investments.overview(USER).missing == ("investment_account",)
    assert services.investments.remove_documents(USER, SESSION) == 0
    removed = [e.draft for e in adapters.audit_log.events() if e.draft.kind is AuditKind.INVESTMENT_DOCUMENTS_REMOVED]
    assert len(removed) == 1 and removed[0].detail == "documents=2"


def test_nothing_about_the_documents_reaches_the_audit_but_counts(services, adapters):
    _drop_both(services)
    details = " ".join(str(e.draft.detail) for e in adapters.audit_log.events())
    for secret in (TRIP, RAINY_DAY, HOLDER, HOLDER_RUT, "422", "385"):
        assert secret not in details, secret
