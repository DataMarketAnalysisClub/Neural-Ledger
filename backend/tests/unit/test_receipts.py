"""ADR-038: what a receipt may prove, how it is identified, and when a statement charge already records it."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from neural_ledger.domain.ledger.categorization import PostedTransaction
from neural_ledger.domain.ledger.entities import Transaction, TransactionKind
from neural_ledger.domain.receipts.model import (
    DocumentKind,
    ReadReceipt,
    ReceiptIssueCode,
    ReceiptStamp,
    StoredReceipt,
    check,
    date_of,
    kind_by_rules,
    match_charges,
    receipt_id,
    total_of,
)

TODAY = date(2026, 10, 29)
STAMP = ReceiptStamp("76543210-3", 39, 4471, date(2026, 10, 29), 12_990, "SUPERMERCADO LOS ANDES SPA", "LECHE")


def _read(**overrides) -> ReadReceipt:
    fields = dict(issuer="SUPERMERCADO LOS ANDES SPA", issued_on=date(2026, 10, 29), total=12_990, folio="4471", issuer_rut="76.543.210-3")
    fields.update(overrides)
    return ReadReceipt(**fields)


def _stored(rid: str, total: int | None = 12_990, on: date | None = date(2026, 10, 29), *, user: str = "camila", issues=()) -> StoredReceipt:
    return StoredReceipt(rid, user, datetime(2026, 10, 29, 12), "STORE", on, total, "CLP", None, False, "text", None, "groceries", "nb", 0.9, issues)


def _charge(txn_id: str, amount: int, on: date, *, user: str = "camila", kind: TransactionKind = TransactionKind.PURCHASE) -> PostedTransaction:
    return PostedTransaction(user, "CLP", Transaction(txn_id, "bank:****1234", on, amount, "COMPRA", "groceries", kind), "stmt_1", 0, "nb", 0.9)


# ---- routing by the printed words ---------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("SUPERMERCADO\nBOLETA ELECTRONICA N° 12\nTOTAL $ 1.000\nVUELTO $ 0", DocumentKind.RECEIPT),
        ("ESTADO DE CUENTA\nSaldo inicial 1.000\nSaldo final 900\nCheques y cargos", DocumentKind.STATEMENT),
        ("CARTOLA HISTORICA\nCuenta corriente\nMovimientos", DocumentKind.STATEMENT),
    ],
)
def test_clear_documents_are_routed_by_their_printed_words(text, kind):
    assert kind_by_rules(text) is kind


@pytest.mark.parametrize("text", ["", "Querida Camila, te escribo para contarte", "boleta y cartola en la misma hoja"])
def test_an_unclear_document_is_left_to_a_decision_model(text):
    assert kind_by_rules(text) is None


# ---- check: what may be counted -----------------------------------------------------------------

def test_a_complete_receipt_has_no_issues():
    assert check(_read(net=10_916, tax=2_074, stamp=STAMP), TODAY) == ()


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"total": None}, ReceiptIssueCode.TOTAL_MISSING),
        ({"total": 0}, ReceiptIssueCode.TOTAL_MISSING),
        ({"issued_on": None}, ReceiptIssueCode.DATE_MISSING),
        ({"issued_on": date(2026, 10, 30)}, ReceiptIssueCode.DATE_IN_FUTURE),
        ({"net": 10_000, "tax": 2_000}, ReceiptIssueCode.TAX_MISMATCH),
        ({"stamp": ReceiptStamp("76543210-3", 39, 4471, date(2026, 10, 29), 19_990)}, ReceiptIssueCode.STAMP_MISMATCH),
        ({"stamp": ReceiptStamp("76543210-3", 39, 4471, date(2026, 10, 28), 12_990)}, ReceiptIssueCode.STAMP_MISMATCH),
    ],
)
def test_a_receipt_that_cannot_be_trusted_names_why(overrides, code):
    assert code in {i.code for i in check(_read(**overrides), TODAY)}


def test_the_stamp_fills_what_the_print_lost_and_its_date_wins():
    read = _read(total=None, issued_on=None, stamp=STAMP)
    assert (total_of(read), date_of(read)) == (12_990, date(2026, 10, 29))
    assert check(read, TODAY) == ()


# ---- identity: the same receipt twice is one receipt ----------------------------------------------

def test_the_same_print_gets_the_same_id_and_another_user_another():
    assert receipt_id("camila", _read()) == receipt_id("camila", _read(issuer="supermercado los andes spa  "))
    assert receipt_id("camila", _read()) != receipt_id("diego", _read())
    assert receipt_id("camila", _read()) != receipt_id("camila", _read(folio="4472"))


def test_a_stamped_receipt_is_identified_by_its_issuer_and_folio_whatever_the_print_says():
    assert receipt_id("camila", _read(stamp=STAMP)) == receipt_id("camila", _read(stamp=STAMP, issuer="SUPERMERC4DO", total=12_000))


# ---- matching a statement charge (no double count) ------------------------------------------------

def test_a_charge_of_the_same_amount_within_three_days_records_the_receipt():
    charges = [_charge("t_far", -12_990, date(2026, 11, 3)), _charge("t_near", -12_990, date(2026, 10, 31))]
    assert match_charges([_stored("r1")], charges) == {"r1": "t_near"}


@pytest.mark.parametrize(
    "charge",
    [
        _charge("t", -12_991, date(2026, 10, 29)),  # another amount
        _charge("t", -12_990, date(2026, 11, 2)),  # four days later
        _charge("t", 12_990, date(2026, 10, 29), kind=TransactionKind.REFUND),  # money back, not a purchase
        _charge("t", -12_990, date(2026, 10, 29), user="diego"),  # someone else's statement
    ],
)
def test_nothing_else_matches(charge):
    assert match_charges([_stored("r1")], [charge]) == {}


def test_each_charge_records_one_receipt_and_unverified_receipts_none():
    from neural_ledger.domain.receipts.model import ReceiptIssue

    receipts = [_stored("r1"), _stored("r2"), _stored("r3", issues=(ReceiptIssue(ReceiptIssueCode.TAX_MISMATCH, "x"),))]
    charges = [_charge("t1", -12_990, date(2026, 10, 29))]
    assert match_charges(receipts, charges) == {"r1": "t1"}


def test_the_answer_does_not_depend_on_the_order_of_the_ledger():
    charges = [_charge("t2", -12_990, date(2026, 10, 30)), _charge("t1", -12_990, date(2026, 10, 28))]
    assert match_charges([_stored("r1")], charges) == match_charges([_stored("r1")], list(reversed(charges))) == {"r1": "t1"}


def test_a_total_with_an_amount_is_a_receipt_when_nothing_says_statement():
    assert kind_by_rules("SOME CAFE\nCAFE 2.500\nTotal $2.500") is DocumentKind.RECEIPT
    assert kind_by_rules("SOME CAFE\nCAFE 2.500\nTota] 82.500") is DocumentKind.RECEIPT  # OCR's TOTAL
    assert kind_by_rules("Saldo final\nTotal cargos 2.500") is DocumentKind.STATEMENT


# ---- the user's corrections ----------------------------------------------------------------------

def test_a_date_typed_by_the_user_settles_a_missing_date_and_marks_the_receipt():
    from neural_ledger.domain.receipts.model import ReceiptIssue, correct

    missing = _stored("r1", on=None, issues=(ReceiptIssue(ReceiptIssueCode.DATE_MISSING, "x"),))
    fixed = correct(missing, None, date(2026, 10, 16), TODAY)
    assert (fixed.issued_on, fixed.verified, fixed.corrected, fixed.receipt_id) == (date(2026, 10, 16), True, True, "r1")


def test_a_total_typed_by_the_user_settles_what_a_total_settles_and_nothing_else():
    from neural_ledger.domain.receipts.model import ReceiptIssue, correct

    issues = (ReceiptIssue(ReceiptIssueCode.TOTAL_MISSING, "x"), ReceiptIssue(ReceiptIssueCode.DATE_MISSING, "y"))
    fixed = correct(_stored("r1", total=None, on=None, issues=issues), 30_000, None, TODAY)
    assert fixed.total == 30_000 and [i.code for i in fixed.issues] == [ReceiptIssueCode.DATE_MISSING]


@pytest.mark.parametrize(
    ("total", "on", "message"),
    [(None, None, "give the total"), (0, None, "between 1"), (100_000_001, None, "between 1"), (None, date(2026, 10, 30), "past day"), (None, date(1999, 12, 31), "from 2000")],
)
def test_corrections_outside_sense_are_refused(total, on, message):
    from neural_ledger.domain.receipts.model import correct

    with pytest.raises(ValueError, match=message):
        correct(_stored("r1"), total, on, TODAY)


# ---- expenses the user tells the copilot about ----------------------------------------------------

@pytest.mark.parametrize(
    ("text", "amount"),
    [("hoy gasté 15 lucas en el almuerzo", 15_000), ("pagué $12.990 con tarjeta", 12_990), ("gasté 800 en el metro", 800), ("spent 25k on dinner", 25_000), ("gasté 1.234.567", 1_234_567)],
)
def test_the_amounts_a_user_wrote(text, amount):
    from neural_ledger.domain.receipts.model import written_amounts

    assert amount in written_amounts(text)


def test_a_cash_expense_is_never_matched_with_a_statement_charge():
    from dataclasses import replace

    cash = replace(_stored("r1"), payment="cash", source="manual")
    card = replace(_stored("r2"), payment="card", source="manual")
    charges = [_charge("t1", -12_990, date(2026, 10, 29)), _charge("t2", -12_990, date(2026, 10, 30))]
    assert match_charges([cash, card], charges) == {"r2": "t1"}
