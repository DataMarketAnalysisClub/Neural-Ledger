"""The Excel pipeline, the card statement layout and the route between them (synthetic samples only)."""

from __future__ import annotations

import io
import zipfile
from datetime import date
from decimal import Decimal

import pytest

from neural_ledger.adapters.outbound.statements import spreadsheet
from neural_ledger.adapters.outbound.statements.banks import BANKS, SHEET_BANKS, detect
from neural_ledger.adapters.outbound.statements.banks.base import cell_money, full_date, parse_money
from neural_ledger.adapters.outbound.statements.banks.bice_xlsx import BiceTarjetaMovimientos
from neural_ledger.adapters.outbound.statements.banks.card_statement import ChileanCardStatement
from neural_ledger.adapters.outbound.statements.banks.santander_xlsx import SantanderCuentaCorrienteXlsx
from neural_ledger.adapters.outbound.statements.ocr_tabular import TableError
from neural_ledger.adapters.outbound.statements.reader import StatementFileReader
from neural_ledger.application.ports import StatementUnreadable
from neural_ledger.domain.ledger.entities import AccountType
from neural_ledger.domain.shared.month import Month
from neural_ledger.domain.statements.model import IssueCode, LineKind, ScheduledAmount, reconcile
from tests.statement_samples import BICE_INTERNATIONAL, CardSample, bice_xlsx, card_pdf, santander_xlsx, xlsx

needs_pdf = pytest.mark.skipif(
    not all(__import__("importlib").util.find_spec(m) for m in ("pymupdf", "pdfplumber")),
    reason="needs the backend's `pdf` extra",
)


def _read(content: bytes):
    return StatementFileReader().read(content)


def test_layout_codes_are_unique_across_families():
    codes = [layout.code for layout in (*BANKS, *SHEET_BANKS)]
    assert len(codes) == len(set(codes))


# ---------------------------------------------------------------- spreadsheet reader
@pytest.mark.parametrize("shared", [True, False])
def test_workbook_cells_keep_their_text_and_columns(shared):
    (sheet,) = spreadsheet.read_workbook(xlsx([["Fecha", None, "Monto"], ["01/09", "x", 8.22], [], [None, None, -120990]], "Datos", shared=shared))
    assert sheet.name == "Datos"
    assert sheet.rows == (("Fecha", "", "Monto"), ("01/09", "x", "8.22"), ("", "", "-120990"))
    assert sheet.right_of("Fecha") == "" and sheet.below("Monto") == "8.22"


def test_xlsx_is_recognized_by_its_bytes_not_its_name():
    assert spreadsheet.is_xlsx(xlsx([["a"]]))
    assert not spreadsheet.is_xlsx(b"%PDF-1.7")
    plain_zip = io.BytesIO()
    with zipfile.ZipFile(plain_zip, "w") as archive:
        archive.writestr("readme.txt", "not a workbook")
    assert not spreadsheet.is_xlsx(plain_zip.getvalue())


def _patched(content: bytes, name: str, body: bytes) -> bytes:
    source, out = zipfile.ZipFile(io.BytesIO(content)), io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for info in source.infolist():
            archive.writestr(info.filename, body if info.filename == name else source.read(info.filename))
    return out.getvalue()


def test_entity_declarations_are_refused():
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaaaaaaaa">]><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>&a;</t></si></sst>'
    with pytest.raises(TableError, match="DOCTYPE"):
        spreadsheet.read_workbook(_patched(xlsx([["a"]]), "xl/sharedStrings.xml", bomb))


def test_too_many_parts_is_refused(monkeypatch):
    monkeypatch.setattr(spreadsheet, "MAX_ENTRIES", 3)
    with pytest.raises(TableError, match="too many parts"):
        spreadsheet.read_workbook(xlsx([["a"]]))


def test_legacy_xls_and_unknown_sheets_are_unreadable_with_a_reason():
    with pytest.raises(StatementUnreadable, match="legacy .xls"):
        _read(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64)
    with pytest.raises(StatementUnreadable, match="spreadsheet; known"):
        _read(xlsx([["Presupuesto familiar"], ["Arriendo", 450000]]))


def test_money_helpers_are_exact_and_strict():
    assert parse_money("$ -323.516", 0) == -323_516
    assert parse_money("US$ 1.000,00", 2) == 100_000 and parse_money("-22,41", 2) == -2_241
    assert parse_money("-267.950\xa0CLP", 0) == -267_950 and parse_money("-28,22\xa0US$", 2) == -2_822
    assert parse_money("", 0) is None
    for bad, decimals in (("22,4", 2), ("1.000,50", 0), ("1.00.000", 0), ("12a", 0)):
        with pytest.raises(TableError):
            parse_money(bad, decimals)
    assert cell_money("8.22", 2) == 822 and cell_money("20", 2) == 2_000 and cell_money("-120990", 0) == -120_990
    with pytest.raises(TableError):
        cell_money("8.225", 2)
    assert full_date("27/08/26") == full_date("27/08/2026") == date(2026, 8, 27)


# ---------------------------------------------------------------- Santander checking account (.xlsx)
def test_santander_xlsx_reads_movements_daily_balances_and_reconciles():
    (statement,) = _read(santander_xlsx())
    assert statement.bank == SantanderCuentaCorrienteXlsx.code and statement.source == "xlsx"
    assert statement.account_type is AccountType.CHECKING and not statement.provisional and statement.obligations is None
    assert (statement.account_ref, statement.statement_number) == ("0-000-00-12345-6", "12")
    assert [line.amount for line in statement.lines] == [-900, 26_000, -8_969, 40_000, -10_000]
    assert statement.lines[0].reference == "2432020" and statement.lines[1].reference is None
    assert [b.on.day for b in statement.daily_balances] == [1, 2, 9, 30]
    assert reconcile(statement).ok


def test_santander_xlsx_misprinted_balances_are_caught():
    (statement,) = _read(santander_xlsx(closing_override=1, daily_override={"02/09": 116_000}))
    codes = [i.code for i in reconcile(statement).issues]
    assert IssueCode.CLOSING_BALANCE in codes and IssueCode.DAILY_BALANCE in codes


def test_santander_xlsx_row_with_both_amounts_is_rejected():
    sheets = spreadsheet.read_workbook(santander_xlsx())
    rows = list(sheets[0].rows)
    header = next(i for i, r in enumerate(rows) if r and r[0] == "FECHA")
    rows[header + 1] = ("01/09", "Sucursal Uno", "Compra", "1", "900", "900", "")
    with pytest.raises(TableError, match="exactly one"):
        SantanderCuentaCorrienteXlsx().parse([spreadsheet.Sheet(sheets[0].name, tuple(rows))])


# ---------------------------------------------------------------- BICE card, unbilled movements (.xlsx)
def test_bice_national_export_is_a_provisional_card_statement():
    (statement,) = _read(bice_xlsx())
    assert statement.bank == BiceTarjetaMovimientos.code
    assert statement.account_type is AccountType.CREDIT_CARD and statement.provisional
    assert (statement.currency, statement.account_ref) == ("CLP", "****Ab3x")
    assert (statement.period_start, statement.period_end) == (date(2026, 9, 23), date(2026, 10, 11))
    assert [line.posted_on for line in statement.lines] == sorted(line.posted_on for line in statement.lines)
    kinds = {line.description: (line.kind, line.amount) for line in statement.lines}
    assert kinds["MONTO CANCELADO"] == (LineKind.PAYMENT, 120_990)
    assert kinds["DL DELIVERY APP REVCOMPRAS"] == (LineKind.REFUND, 3_996)
    assert kinds["STORE TWO COMPRAS"] == (LineKind.PURCHASE, -78_578)
    assert statement.lines[0].installment.total == 1
    assert (statement.summary.total_debits, statement.summary.total_credits) == (93_778, 124_986)
    assert reconcile(statement).ok


def test_bice_international_export_is_in_usd_cents():
    (statement,) = _read(bice_xlsx(BICE_INTERNATIONAL, international=True))
    assert statement.currency == "USD"
    assert sorted(line.amount for line in statement.lines) == [-2_000, -822, 2_822]
    assert reconcile(statement).ok


def test_bice_total_that_does_not_match_the_rows_is_caught():
    (statement,) = _read(bice_xlsx(totals_override=("-124.986 CLP", "93.000 CLP")))
    assert [i.code for i in reconcile(statement).issues] == [IssueCode.TOTAL_DEBITS]


# ---------------------------------------------------------------- card statement PDF (A–G format)
@needs_pdf
def test_card_pdf_holds_a_national_and_an_international_statement():
    national, international = _read(card_pdf())
    assert isinstance(detect("estado de cuenta nacional de tarjeta de credito periodo facturado"), ChileanCardStatement)
    for statement in (national, international):
        assert statement.bank == ChileanCardStatement.code and statement.account_type is AccountType.CREDIT_CARD
        assert statement.account_ref == "****4321" and not statement.provisional
        assert reconcile(statement).ok, reconcile(statement).issues
    assert (national.currency, international.currency) == ("CLP", "USD")
    assert (national.period_start, national.period_end) == (date(2026, 7, 30), date(2026, 8, 27))
    # The debt is the holder's negative balance: 100.000 billed before, 45.442 billed now.
    assert (national.summary.opening_balance, national.summary.closing_balance) == (-100_000, -45_442)
    assert [(i.amount, i.kind) for i in international.lines] == [(2_241, LineKind.PAYMENT), (-1_000, LineKind.PURCHASE), (-899, LineKind.PURCHASE)]


@needs_pdf
def test_card_pdf_lines_keep_kind_section_and_cuotas():
    national, _ = _read(card_pdf())
    by_section: dict = {}
    for line in national.lines:
        by_section.setdefault(line.section, []).append(line)
    assert [(line.amount, line.kind) for line in by_section["B"]] == [(100_000, LineKind.PAYMENT)]
    assert [(line.amount, line.kind) for line in by_section["G"]] == [(4_850, LineKind.REFUND), (-4_904, LineKind.FEE)]
    store, gadget = by_section["E"]
    assert store.amount == -10_000 and store.posted_on == national.period_end  # an older purchase's cuota, billed now
    assert (store.installment.number, store.installment.total, store.installment.original_amount) == (2, 3, 30_000)
    assert store.installment.monthly_rate == Decimal(0) and store.installment.purchased_on == date(2026, 6, 15)
    assert store.description == "MERCADOPAGO*STORE" and store.branch == "LAS CONDES"
    assert gadget.installment.number == 1


@needs_pdf
def test_card_pdf_obligations_are_read_and_the_printed_schedule_is_checked():
    national, international = _read(card_pdf())
    o = national.obligations
    assert (o.amount_due, o.minimum_due, o.due_date) == (45_442, 5_000, date(2026, 9, 15))
    assert (o.credit_limit, o.credit_used, o.credit_available) == (500_000, 300_000, 200_000)
    assert o.upcoming == (
        ScheduledAmount(Month(2026, 9), 27_633),  # STORE 3/3 (10.000) + GADGET 2/3 (17.633)
        ScheduledAmount(Month(2026, 10), 17_634),  # GADGET 3/3 absorbs the rounding: 52.900 - 2 × 17.633
        ScheduledAmount(Month(2026, 11), 0),
        ScheduledAmount(Month(2026, 12), 0),
    )
    assert (international.obligations.amount_due, international.obligations.minimum_due) == (1_899, None)


@needs_pdf
def test_card_pdf_misprinted_schedule_is_an_issue():
    national, _ = _read(card_pdf(CardSample(upcoming=(27_633, 17_633, 0, 0))))
    (issue,) = reconcile(national).issues
    assert (issue.code, issue.expected, issue.found) == (IssueCode.INSTALLMENT_SCHEDULE, 17_633, 17_634)


@needs_pdf
def test_card_pdf_misprinted_section_total_is_an_issue():
    national, _ = _read(card_pdf(CardSample(section_override={"D": 17_000})))
    (issue,) = reconcile(national).issues
    assert (issue.code, issue.expected, issue.found) == (IssueCode.SECTION_TOTAL, -17_000, -17_755)


@needs_pdf
def test_card_pdf_line_the_layout_cannot_read_breaks_its_section_instead_of_vanishing():
    national, _ = _read(card_pdf(CardSample(drop_line="CAFE TWO SANTIAGO")))
    assert [i.code for i in reconcile(national).issues] == [IssueCode.SECTION_TOTAL, IssueCode.CLOSING_BALANCE]


@needs_pdf
def test_card_pdf_without_the_international_page_is_one_statement():
    (national,) = _read(card_pdf(CardSample(international=False)))
    assert national.currency == "CLP"
