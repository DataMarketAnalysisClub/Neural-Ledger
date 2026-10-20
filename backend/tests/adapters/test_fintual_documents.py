"""The Fintual document reader (ADR-044) on synthetic PDFs laid out like the real ones (tests/investment_samples.py)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

pytest.importorskip("pymupdf")
pytest.importorskip("pdfplumber")

from neural_ledger.adapters.outbound.investments.fintual_documents import FintualDocumentReader  # noqa: E402
from neural_ledger.adapters.outbound.receipts.reader import ReceiptFileReader  # noqa: E402
from neural_ledger.application.ports import InvestmentDocumentReader, StatementUnreadable  # noqa: E402
from neural_ledger.domain.investments.documents import InvestmentDocumentKind, check_document  # noqa: E402
from neural_ledger.domain.receipts.model import DocumentKind, kind_by_rules  # noqa: E402
from tests.investment_samples import (  # noqa: E402
    HOLDER,
    HOLDER_RUT,
    HOME,
    STATEMENT_DAY,
    TRIP,
    _pdf,
    holdings_pdf,
    movement_rows,
    movements_pdf,
)
from tests.receipt_samples import boleta_pdf  # noqa: E402

READER = FintualDocumentReader()
TODAY = date(2026, 10, 19)


def test_it_is_a_document_reader():
    assert isinstance(READER, InvestmentDocumentReader)


def test_the_statement_is_read_row_by_row_with_its_day():
    read = READER.read(holdings_pdf())
    assert read.kind is InvestmentDocumentKind.HOLDINGS and read.as_of == STATEMENT_DAY and read.total == 422_097
    first = read.positions[0]
    assert (first.fund, first.series, first.shares, first.share_value, first.balance) == ("Risky Norris", "A", Decimal("62.7235"), Decimal("4800.0000"), 301_073)
    assert [p.fund for p in read.positions][-2:] == ["Very Conservative Streep", "Moderate Brad 107"]  # funds with no shares too
    assert check_document(read, TODAY) == ()


def test_the_certificate_is_read_row_by_row():
    read = READER.read(movements_pdf())
    assert read.kind is InvestmentDocumentKind.MOVEMENTS and len(read.movements) == 11
    newest = read.movements[0]
    assert (newest.day, newest.goal, newest.fund, newest.series) == (date(2026, 9, 15), HOME, "Moderate Pitt", "A")
    assert (newest.shares_in, newest.shares_out, newest.pesos_in, newest.pesos_out, newest.internal) == (Decimal("20.0000"), 0, 45_000, 0, False)
    moves = [m for m in read.movements if m.internal]
    assert {(m.fund, m.pesos_in, m.pesos_out) for m in moves} == {("Moderate Pitt", 33_000, 0), ("Very Conservative Streep", 0, 33_000)}
    assert {m.goal for m in read.movements} == {TRIP, HOME, "Fondo de emergencia"}  # accents survive the text layer
    assert check_document(read, TODAY) == ()


def test_a_goal_name_that_holds_fund_words_is_split_from_the_right():
    rows = [row.replace(TRIP, "Plan Risky Moderate de largo plazo risky") for row in movement_rows()]
    read = READER.read(movements_pdf(rows=rows))
    assert {m.goal for m in read.movements if m.fund == "Risky Norris" and m.pesos_in == 100_000} == {"Plan Risky Moderate de largo plazo risky"}
    assert check_document(read, TODAY) == ()


def test_the_holder_is_never_read():
    for content in (holdings_pdf(), movements_pdf()):
        read = repr(READER.read(content))
        assert HOLDER not in read and HOLDER_RUT not in read and "Valentina" not in read


def test_both_documents_route_as_investments_and_receipts_still_route_as_receipts():
    peek = ReceiptFileReader().peek
    assert kind_by_rules(peek(holdings_pdf()).text) is DocumentKind.INVESTMENT
    assert kind_by_rules(peek(movements_pdf()).text) is DocumentKind.INVESTMENT
    assert kind_by_rules(peek(boleta_pdf()).text) is DocumentKind.RECEIPT


def test_a_row_that_does_not_parse_makes_the_file_unreadable():
    rows = movement_rows()
    rows[2] = rows[2].replace("Transferencia electronica", "Transferencia electronica 12")
    with pytest.raises(StatementUnreadable, match="movement"):
        READER.read(movements_pdf(rows=rows))
    unknown_fund = [row.replace("Moderate Pitt", "Global Fund") for row in movement_rows()]
    with pytest.raises(StatementUnreadable):
        READER.read(movements_pdf(rows=unknown_fund))


@pytest.mark.parametrize(
    "content",
    [
        b"not a pdf at all",
        boleta_pdf(),  # a PDF, but not Fintual's
        _pdf(["Fintual Administradora General de Fondos", "Carta de bienvenida"]),  # Fintual's, but neither document
    ],
    ids=["not-a-pdf", "a-receipt", "another-fintual-letter"],
)
def test_other_files_are_unreadable(content):
    with pytest.raises(StatementUnreadable):
        READER.read(content)


def test_a_spanish_statement_day_is_read_too():
    lines = [
        "CERTIFICADO DE SALDOS",
        f"Fintual Administradora General de Fondos S.A. certifica que al 14 de octubre de 2026 {HOLDER}, RUT {HOLDER_RUT}, mantenía:",
        "Fondo Serie Cuotas Valor Cuota Saldo",
        "FM Fintual Risky Norris A 10,0000 $4.800,0000 $48.000",
        "Total $48.000",
    ]
    read = READER.read(_pdf(lines))
    assert read.kind is InvestmentDocumentKind.HOLDINGS and read.as_of == date(2026, 10, 14) and read.total == 48_000
    assert check_document(read, TODAY) == ()


def test_a_tampered_total_is_read_as_printed_and_fails_the_check():
    read = READER.read(holdings_pdf(total_delta=1_000))
    assert read.total == 423_097 and check_document(read, TODAY)
