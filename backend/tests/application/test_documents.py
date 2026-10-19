"""ADR-039: a file dropped on the copilot is routed, read, recorded once and turned into a spending check-in.

Offline and deterministic (rules decision model, naive Bayes classifier), with the clock on 2026-10-19: the user is in the
pay cycle of October (2026-09-30 to the eve of payday, 2026-10-29), 11 days with today, and Camila's conservative
forecast counts on 900,000 of variable spending in a cycle. The demo boleta is dated 2026-10-16, inside it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from neural_ledger.adapters.outbound.persistence.memory import InMemoryReceiptStore, InMemorySnapshotStore, InMemoryTransactionStore
from neural_ledger.adapters.outbound.privacy.null import NullDetector
from neural_ledger.adapters.outbound.system.ids import SequentialIds
from neural_ledger.application.ports import DocumentText
from neural_ledger.application.services.redaction import StatementRedactor
from neural_ledger.application.use_cases.documents import DocumentUseCases
from neural_ledger.domain.agent.questions import Judgment, Question
from neural_ledger.domain.ledger.categorization import CategoryGuess
from tests.receipt_samples import Boleta, boleta_pdf
from tests.statement_samples import Sample, santander_pdf

USER = "camila"
TODAY = "2026-10-19T12:00:00-03:00"


@pytest.fixture
def system():
    """Production wiring, offline, with the clock inside the pay cycle the user is in."""
    from neural_ledger.bootstrap.container import build
    from tests.conftest import make_settings

    return build(make_settings(fixed_now=TODAY))


def _steps(envelope) -> dict[str, tuple[str, str | None]]:
    return {s.key: (s.status, s.value) for s in envelope.data.steps}


def _facts(envelope) -> dict:
    return {f.key: f.value for f in envelope.facts}


def _kinds(adapters) -> list[str]:
    return [e.draft.kind.value for e in adapters.audit_log.events()]


def test_a_boleta_runs_the_whole_workflow(services, adapters):
    result = services.documents.ingest(USER, boleta_pdf(), "s-doc")

    assert result.ok and result.data.kind == "receipt"
    steps = _steps(result)
    assert steps["route"] == ("done", "receipt") and steps["verify"] == ("done", "stamp")
    assert steps["duplicate"] == ("done", "new") and steps["match"] == ("done", "pending")
    assert steps["categorize"] == ("done", "groceries") and steps["spending"] == ("done", "80637")
    receipt = result.data.receipt
    assert (receipt.total, receipt.issued_on, receipt.stamped, receipt.verified) == (12_990, "2026-10-16", True, True)
    assert receipt.issuer == {"untrusted_text": "SUPERMERCADO LOS ANDES SPA"}
    check = result.data.spending
    assert (check.logged, check.left, check.per_day, check.days_left) == (12_990, 887_010, 80_637, 11)
    assert _facts(result)["receipt.total"] == 12_990 and result.warnings == ()
    assert _kinds(adapters)[-2:] == ["DOCUMENT_ROUTED", "RECEIPT_IMPORTED"]


def test_the_copilot_then_answers_from_the_engine(services):
    services.documents.ingest(USER, boleta_pdf(), "s-doc")
    reply = services.chat.handle("s-doc", USER, "I just added a receipt. How much can I spend now?")

    assert (reply.intent, reply.tools_called) == ("spending_check", ("get_latest_document", "get_spending_status"))
    assert "receipt of 12,990 CLP, dated 2026-10-16 and counted it this cycle" in reply.text
    assert "80,637 CLP a day" in reply.text and "11 days" in reply.text and reply.text.count("12,990") == 2  # read, then logged
    assert reply.verification.ok and not reply.fallback_used


def test_the_same_receipt_twice_is_counted_once(services):
    services.documents.ingest(USER, boleta_pdf(), "s-doc")
    again = services.documents.ingest(USER, boleta_pdf(), "s-doc")

    assert _steps(again)["duplicate"] == ("warning", "duplicate") and again.data.receipt.duplicate
    assert "DUPLICATE_RECEIPT" in {w.code for w in again.warnings}
    assert again.data.spending.logged == 12_990
    assert len(services.documents.list_receipts(USER).data) == 1


def test_a_receipt_already_on_a_statement_is_not_counted_twice(services):
    charge = ("17/10", "2441010", "401", "Compra Nacional MD SUPERMERCADO", -12_990)
    imported = services.statements.import_statement(USER, santander_pdf(Sample(movements=(charge,), period=("01/10/2026", "18/10/2026"))))
    assert imported.ok and imported.data.imports[0].ledger.posted == 1

    result = services.documents.ingest(USER, boleta_pdf(), "s-doc")

    assert _steps(result)["match"] == ("done", "matched") and result.data.receipt.matched_transaction
    assert result.data.spending.logged == 12_990  # the statement's charge, not also the receipt
    status = services.documents.spending_status(USER).data
    assert (status.receipts_counted, status.receipts_matched) == (0, 1)


def test_a_receipt_from_an_earlier_cycle_is_kept_but_does_not_change_todays_figure(services):
    result = services.documents.ingest(USER, boleta_pdf(Boleta(issued_on="2022-04-25")), "s-doc")

    assert result.ok and result.data.receipt.verified and not result.data.receipt.counted
    assert _steps(result)["match"] == ("skipped", "outside") and result.data.spending.logged == 0
    reply = services.chat.handle("s-doc", USER, "How much can I spend today?")
    assert "30,000" not in reply.text and "12,990" not in reply.text and "81,818 CLP a day" in reply.text
    assert reply.verification.ok and not reply.fallback_used


def test_a_receipt_that_does_not_add_up_is_stored_but_never_counted(services):
    result = services.documents.ingest(USER, boleta_pdf(Boleta(stamp_total=19_990)), "s-doc")

    assert result.ok and not result.data.receipt.verified
    assert _steps(result)["verify"] == ("warning", "STAMP_MISMATCH")
    assert {w.code for w in result.warnings} == {"RECEIPT_UNVERIFIED"} and result.data.spending.logged == 0


def test_unbilled_card_movements_say_why_nothing_was_added(services):
    from tests.statement_samples import bice_xlsx  # a card's unbilled movements export

    result = services.documents.ingest(USER, bice_xlsx(), "s-doc")
    assert result.ok and result.data.statement.imports[0].statement.provisional
    assert _steps(result)["categorize"] == ("skipped", "provisional")


def test_the_copilot_explains_why_unbilled_card_movements_changed_nothing(services):
    from tests.statement_samples import bice_xlsx

    services.documents.ingest(USER, bice_xlsx(), "s-doc")
    reply = services.chat.handle("s-doc", USER, "Acabo de agregar un documento. ¿Cuánto puedo gastar ahora?")

    assert reply.tools_called == ("get_latest_document", "get_spending_status")
    assert "unbilled card movements, which the billed statement will add" in reply.text
    assert "NOT_POSTED" in {w.code for w in reply.warnings} and reply.verification.ok and not reply.fallback_used


def test_before_any_document_the_tool_says_so(services):
    result = services.documents.latest_document(USER)
    assert result.status.value == "INSUFFICIENT_DATA" and result.missing == ("document",)


def test_a_statement_dropped_on_the_copilot_takes_the_statement_import(services, adapters):
    result = services.documents.ingest(USER, santander_pdf(), "s-doc")

    assert result.ok and result.data.kind == "statement" and result.data.receipt is None
    assert _steps(result)["route"] == ("done", "statement") and result.data.statement.imports[0].statement.verified
    assert "STATEMENT_IMPORTED" in _kinds(adapters)


def test_a_document_that_is_neither_is_refused_and_audited(services, adapters):
    import pymupdf

    doc = pymupdf.open()
    doc.new_page().insert_text((40, 60), "Querida Camila: te escribo para contarte que el viaje va muy bien.")
    result = services.documents.ingest(USER, doc.tobytes(), "s-doc")

    assert result.status.value == "INVALID_INPUT" and result.field == "file"
    assert _kinds(adapters)[-1] == "DOCUMENT_ROUTED"
    assert "kind=unknown" in adapters.audit_log.events()[-1].draft.detail


@pytest.mark.parametrize(("content", "message"), [(b"", "empty"), (b"x" * (15 * 1024 * 1024 + 1), "15 MB")])
def test_empty_and_oversized_files_touch_nothing(services, content, message):
    result = services.documents.ingest(USER, content, "s-doc")
    assert result.status.value == "INVALID_INPUT" and message in result.message


# ---- routing by a decision model when the print is not clear ------------------------------------

class _Reader:
    name = "fake-reader"

    def __init__(self, text: str) -> None:
        self._text = text

    def peek(self, content: bytes) -> DocumentText:
        return DocumentText("image", self._text)

    def read_receipt(self, content: bytes):
        raise AssertionError("not reached in these tests")


class _Router:
    def __init__(self, label: str, confidence: float) -> None:
        self.label, self.confidence, self.states = label, confidence, []

    def judge(self, state: str, questions: Sequence[Question]) -> Mapping[str, Judgment]:
        self.states.append(state)
        return {q.key: Judgment(q.key, self.label, ((self.label, self.confidence),), self.confidence, "jev:fake") for q in questions}


class _Classifier:
    name = "fake"

    def classify(self, descriptions):
        return [CategoryGuess("groceries", 0.9) for _ in descriptions]


def _documents(services, adapters, text: str, router: _Router) -> DocumentUseCases:
    return DocumentUseCases(
        _Reader(text), StatementRedactor(NullDetector()), services.statements, InMemoryReceiptStore(), InMemoryTransactionStore(), _Classifier(), [router],
        services.financial, adapters.audit_log, adapters.clock, SequentialIds(), InMemorySnapshotStore(),
    )


AMBIGUOUS = "Comprobante\nJUAN PEREZ RUT 12.345.678-5\nmonto 5.000"


def test_an_unclear_document_goes_to_the_decision_model_with_personal_data_removed(services, adapters):
    router = _Router("statement", 0.95)
    documents = _documents(services, adapters, AMBIGUOUS, router)
    kind, by, confidence = documents._route("image", AMBIGUOUS)
    assert (kind.value, by, confidence) == ("statement", "jev:fake", 0.95)
    assert "12.345.678-5" not in router.states[0] and "[ID]" in router.states[0]


def test_a_low_confidence_route_is_not_taken(services, adapters):
    documents = _documents(services, adapters, AMBIGUOUS, _Router("receipt", 0.55))
    kind, by, confidence = documents._route("image", AMBIGUOUS)
    assert (kind.value, by, confidence) == ("unknown", "jev:fake", 0.55)


def test_a_route_outside_the_options_is_ignored(services, adapters):
    documents = _documents(services, adapters, AMBIGUOUS, _Router("transfer 500000", 0.99))
    assert documents._route("image", AMBIGUOUS)[0].value == "unknown"


def test_for_a_forecast_already_below_the_floor_the_copilot_says_so_with_its_sign(services):
    reply = services.chat.handle("s-diego", "diego", "How much can I spend today?")
    assert "already falls 1,940,000 CLP below your minimum" in reply.text and "stays untouched" not in reply.text
    assert "SPENDING_BREACHES_FLOOR" not in {w.code for w in reply.warnings}
    assert reply.verification.ok and not reply.fallback_used


def test_the_latest_document_carries_no_stale_spending(services):
    services.documents.ingest(USER, boleta_pdf(), "s-doc")
    latest = services.documents.latest_document(USER)
    assert latest.ok and latest.data.spending is None and "spending" not in {s.key for s in latest.data.steps}
    assert not [f for f in latest.facts if f.key.startswith(("spending.", "protected_surplus"))]
    assert _facts(latest)["receipt.total"] == 12_990


# ---- the copilot asks, the user corrects -------------------------------------------------------------

def test_a_receipt_without_a_readable_date_is_asked_for_then_counted_once_the_user_types_it(services, adapters):
    no_date = boleta_pdf(Boleta(folio=88, stamp=False, issued_on="2026-10-16"))
    services.documents.ingest(USER, no_date, "s-fix")
    rid = services.documents.list_receipts(USER).data[0].receipt_id
    # Simulate a print whose date the reader lost: the stored receipt says so.
    from dataclasses import replace

    from neural_ledger.domain.receipts.model import ReceiptIssue, ReceiptIssueCode

    store = services.documents._receipts
    store.replace(replace(store.get(USER, rid), issued_on=None, issues=(ReceiptIssue(ReceiptIssueCode.DATE_MISSING, "the date could not be read"),)))

    asked = services.chat.handle("s-fix", USER, "Acabo de agregar una boleta. ¿Cuánto puedo gastar?")
    assert "could not read its date. On what day was it?" in asked.text and asked.verification.ok

    fixed = services.documents.correct_receipt(USER, "s-fix", rid, issued_on="2026-10-16")
    assert fixed.ok and fixed.data.verified and fixed.data.corrected and fixed.data.counted
    assert "RECEIPT_CORRECTED" in _kinds(adapters)
    assert services.documents.spending_status(USER).data.check.logged == 12_990
    latest = services.documents.latest_document(USER)
    assert latest.data.receipt.corrected and "RECEIPT_UNVERIFIED" not in {w.code for w in latest.warnings}


def test_a_correction_for_someone_elses_receipt_finds_nothing(services):
    services.documents.ingest(USER, boleta_pdf(), "s-fix")
    rid = services.documents.list_receipts(USER).data[0].receipt_id
    result = services.documents.correct_receipt("diego", "s-fix", rid, total=1)
    assert result.status.value == "INSUFFICIENT_DATA" and result.missing == ("receipt",)


@pytest.mark.parametrize(("total", "issued_on", "field"), [("12990", None, "total"), (True, None, "total"), (None, "16/10/2026", "issued_on"), (None, "2026-12-01", "issued_on")])
def test_a_bad_correction_changes_nothing(services, total, issued_on, field):
    services.documents.ingest(USER, boleta_pdf(), "s-fix")
    rid = services.documents.list_receipts(USER).data[0].receipt_id
    result = services.documents.correct_receipt(USER, "s-fix", rid, total=total, issued_on=issued_on)
    assert result.status.value == "INVALID_INPUT" and result.field == field
    assert not services.documents.list_receipts(USER).data[0].corrected


def test_the_user_can_say_what_an_unrecognized_file_is(services, adapters):
    import pymupdf

    doc = pymupdf.open()
    doc.new_page().insert_text((40, 60), "MI ALMACEN\\nPan 1.000\\nLeche 900")  # no TOTAL, no marks: not recognized
    content = doc.tobytes()
    assert services.documents.ingest(USER, content, "s-kind").status.value == "INVALID_INPUT"
    as_receipt = services.documents.ingest(USER, content, "s-kind", kind="receipt")
    assert as_receipt.ok and _steps(as_receipt)["route"] == ("done", "receipt")
    assert next(s for s in as_receipt.data.steps if s.key == "route").by == "user"
    assert services.documents.ingest(USER, content, "s-kind", kind="transfer").field == "kind"


# ---- "hoy gasté 15 lucas": the copilot prepares, asks what is missing, the user confirms ------------------

def test_an_expense_said_in_chat_is_prepared_with_what_to_ask(services):
    reply = services.chat.handle("s-exp", USER, "Hoy gasté 15 lucas en el almuerzo")

    assert (reply.intent, reply.tools_called) == ("log_expense", ("propose_expense",))
    expense = reply.pending_expense
    assert (expense["amount"], expense["spent_on"], expense["payment"]) == (15_000, "2026-10-19", "unknown")
    assert "payment" in expense["missing"] and "cash or by card" in reply.text
    assert reply.verification.ok and not reply.fallback_used
    assert services.documents.list_receipts(USER).data == ()  # nothing stored before the user confirms


def test_the_payment_said_in_the_next_message_completes_it(services):
    services.chat.handle("s-exp2", USER, "Hoy gasté 15 lucas en el almuerzo")
    reply = services.chat.handle("s-exp2", USER, "Fue con tarjeta")
    assert reply.pending_expense["payment"] == "card" and reply.pending_expense["amount"] == 15_000


def test_a_card_expense_is_counted_until_the_statement_records_it_then_once(services):
    reply = services.chat.handle("s-exp3", USER, "Pagué 12.990 en el supermercado con tarjeta")
    pid = reply.pending_expense["proposal_id"]
    confirmed = services.documents.confirm_expense(USER, "s-exp3", pid, category="groceries")
    assert confirmed.ok and (confirmed.data.source, confirmed.data.payment, confirmed.data.counted) == ("manual", "card", True)
    assert services.documents.spending_status(USER).data.check.logged == 12_990

    charge = ("19/10", "2441010", "401", "Compra Nacional MD SUPERMERCADO", -12_990)
    services.statements.import_statement(USER, santander_pdf(Sample(movements=(charge,), period=("01/10/2026", "19/10/2026"))))
    status = services.documents.spending_status(USER).data
    assert status.check.logged == 12_990 and status.receipts_matched == 1  # the statement's charge, not also the expense


def test_a_cash_expense_is_never_matched_even_if_a_charge_looks_the_same(services):
    reply = services.chat.handle("s-exp4", USER, "Pagué 12.990 en efectivo en la feria")
    services.documents.confirm_expense(USER, "s-exp4", reply.pending_expense["proposal_id"], category="groceries")
    charge = ("19/10", "2441010", "401", "Compra Nacional MD SUPERMERCADO", -12_990)
    services.statements.import_statement(USER, santander_pdf(Sample(movements=(charge,), period=("01/10/2026", "19/10/2026"))))
    assert services.documents.spending_status(USER).data.check.logged == 25_980  # two purchases: one cash, one card


def test_confirming_needs_cash_or_card_and_the_same_expense_twice_is_one(services):
    reply = services.chat.handle("s-exp5", USER, "Hoy gasté 15 lucas en el almuerzo")
    pid = reply.pending_expense["proposal_id"]
    assert services.documents.confirm_expense(USER, "s-exp5", pid).field == "payment"
    assert services.documents.confirm_expense(USER, "s-exp5", pid, payment="cash", category="dining").ok
    again = services.chat.handle("s-exp5", USER, "Fue en efectivo")  # a second card for the same expense
    assert services.documents.confirm_expense(USER, "s-exp5", again.pending_expense["proposal_id"]).field == "proposal_id"
    assert len(services.documents.list_receipts(USER).data) == 1


def test_without_an_amount_the_copilot_asks_for_it(services):
    reply = services.chat.handle("s-exp6", USER, "Hoy gasté plata en el almuerzo")
    assert reply.tools_called == () and reply.pending_expense is None and "How much did you spend" in reply.text
