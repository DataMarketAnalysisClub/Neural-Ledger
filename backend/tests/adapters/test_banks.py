"""Bank layouts: recognize the cartola, read every row, and stay strict about what does not fit."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from neural_ledger.adapters.outbound.statements.banks import BANKS, detect
from neural_ledger.adapters.outbound.statements.banks.base import day_month, parse_clp
from neural_ledger.adapters.outbound.statements.banks.santander import SantanderCuentaMatica
from neural_ledger.adapters.outbound.statements.ocr_tabular import Table, TableError, read_pages, rebuild
from neural_ledger.domain.statements.model import IssueCode, reconcile
from tests.statement_samples import DEFAULT_MOVEMENTS, Sample, santander_pdf

REAL_CARTOLAS = Path(__file__).resolve().parents[3] / "cartolas"

needs_pdf = pytest.mark.skipif(
    not all(__import__("importlib").util.find_spec(m) for m in ("pymupdf", "pdfplumber")),
    reason="needs the backend's `pdf` extra",
)


def _read(content: bytes):
    pages = read_pages(content)
    bank = detect(pages[0].text)
    assert bank is not None
    return bank.parse([rebuild(p, bank.table) for p in pages])


def test_bank_codes_are_unique():
    codes = [bank.code for bank in BANKS]
    assert len(codes) == len(set(codes))


@needs_pdf
def test_santander_is_recognized_and_others_are_not():
    assert isinstance(detect(read_pages(santander_pdf())[0].text), SantanderCuentaMatica)
    assert detect("BANCO DESCONOCIDO cartola de cuenta corriente") is None


@needs_pdf
def test_synthetic_santander_reads_every_movement_across_pages():
    statement = _read(santander_pdf())
    assert statement.bank == "santander_cl_cuentamatica"
    assert statement.account_ref == "0-000-00-12345-6"
    assert (statement.period_start, statement.period_end) == (date(2025, 11, 30), date(2026, 1, 5))
    assert [(line.description, line.amount) for line in statement.lines] == [(m[3], m[4]) for m in DEFAULT_MOVEMENTS]
    assert statement.lines[-1].posted_on == date(2026, 1, 5)  # year inferred from the period
    assert statement.lines[0].reference == "2441010" and statement.lines[2].reference is None
    assert statement.lines[2].branch == "90"
    assert len(statement.daily_balances) == 5
    assert statement.source == "text" and all(line.confidence is None for line in statement.lines)
    assert reconcile(statement).ok


@needs_pdf
def test_misprinted_totals_are_read_as_printed_and_caught_by_reconciliation():
    # The real charges add up to 61,080; the printed totals are consistent with each other but say 61,000.
    statement = _read(santander_pdf(Sample(summary_override=(1_000_000, 61_000, 463_521, 1_402_521))))
    assert statement.summary.total_debits == 61_000
    assert [i.code for i in reconcile(statement).issues] == [IssueCode.TOTAL_DEBITS]


@needs_pdf
def test_wrong_daily_balance_is_caught_on_its_day_and_the_next():
    # Reconciliation resyncs to each printed balance (so one bad line is reported once); a misprinted
    # balance therefore shows on its own day and on the day after, and nowhere else.
    statement = _read(santander_pdf(Sample(daily_override={"04/12": 1_154_942})))
    issues = reconcile(statement).issues
    assert [(i.code, i.on) for i in issues] == [(IssueCode.DAILY_BALANCE, date(2025, 12, 4)), (IssueCode.DAILY_BALANCE, date(2025, 12, 15))]


def _table(data: list[list[str]]) -> Table:
    preamble = [
        ["0-000-00-12345-6", "77", "30/11/2025", "05/01/2026", "1", "DE", "1"],
        ["Saldo", "Inicial", "Cheques", "o", "Cargos", "Depósitos", "o", "Abonos", "Saldo", "Final"],
        ["1.000", "0", "0", "1.000"],
    ]
    header = ["FECHA", "NUMERO", "SUC", "DESCRIPCION", "CHEQUES Y CARGOS", "DEPOSITOS Y ABONOS", "SALDO"]
    return Table(rows=[*preamble, header, *data], header_index=len(preamble), source="text", page=1)


@pytest.mark.parametrize(
    "row",
    [
        ["02/12", "", "401", "Compra", "3.2B0", "", ""],  # OCR-style misread amount
        ["02/12", "", "401", "Compra", "3.280", "1.000", ""],  # both columns
        ["", "123", "401", "Compra", "", "", ""],  # no amount, not a continuation
        ["31/02", "", "401", "Compra", "3.280", "", ""],  # impossible date
    ],
)
def test_rows_that_do_not_fit_the_layout_are_rejected(row):
    with pytest.raises(TableError):
        SantanderCuentaMatica().parse([_table([row])])


def test_wrapped_description_joins_the_previous_line():
    statement = SantanderCuentaMatica().parse(
        [_table([["02/12", "", "401", "Compra Nacional MD", "3.280", "", ""], ["", "", "", "LONG MERCHANT", "", "", ""]])]
    )
    assert [line.description for line in statement.lines] == ["Compra Nacional MD LONG MERCHANT"]


def test_amount_and_date_helpers():
    assert parse_clp("1.116.492") == 1_116_492
    assert parse_clp("$ 300.000") == 300_000
    assert parse_clp("") is None
    with pytest.raises(TableError):
        parse_clp("1.11.492")
    with pytest.raises(TableError):
        parse_clp("3.2B0")
    assert day_month("15/12", date(2026, 1, 15)) == date(2025, 12, 15)
    assert day_month("02/09", date(2026, 9, 30)) == date(2026, 9, 2)


@needs_pdf
@pytest.mark.skipif(not any(REAL_CARTOLAS.glob("*.pdf")), reason="no local cartolas/ (never committed)")
def test_local_real_cartolas_reconcile():
    """Runs only on a developer machine. Asserts nothing about the contents (personal data)."""
    for path in sorted(REAL_CARTOLAS.glob("*.pdf")):
        statement = _read(path.read_bytes())
        assert statement.lines, path.name
        assert reconcile(statement).ok, path.name


@pytest.mark.parametrize(
    "noisy, value",
    [("3 280", 3_280), ("4 . 180", 4_180), ("1 _ 097 .805", 1_097_805), ("1 .065 119", 1_065_119), ("32490", 32_490)],
)
def test_ocr_separator_noise_is_tolerated(noisy, value):
    """Seen on a scanned Santander cartola: separators lost, spaced, or read as '_'."""
    assert parse_clp(noisy) == value


@pytest.mark.parametrize("noisy, day", [("102/09", 2), ("|16/09", 16), ("10/09", 10)])
def test_ocr_table_rule_before_the_date_is_ignored(noisy, day):
    assert day_month(noisy, date(2026, 9, 30)) == date(2026, 9, day)


def test_ocr_table_with_noisy_cells_parses_and_keeps_confidence():
    table = _table([["102/12", "2441010", "ko1", "Compra Nacional MD SH0P", "3 .580", "", ""], ["", "", "", "--- Saldo Dia ---", "", "", "996 _ 420"]])
    table.source = "ocr"
    table.confidences = [[1.0] * 10 for _ in table.rows[: table.header_index + 1]] + [
        [0.9, 0.99, 0.2, 0.7, 0.4, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.9, 0.0, 0.0, 0.95],
    ]
    statement = SantanderCuentaMatica().parse([table])
    (line,) = statement.lines
    assert (line.posted_on, line.amount, line.branch, line.confidence) == (date(2025, 12, 2), -3_580, "ko1", 0.2)
    assert statement.daily_balances[0].balance == 996_420 and statement.source == "ocr"
