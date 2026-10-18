"""Banco Santander Chile, 'Estado CuentaMática' (checking account cartola).

Layout, every page:
    preamble   holder and address (never read), then
               CARTOLA DESDE HASTA PAGINA
               <account> <number> <dd/mm/yyyy> <dd/mm/yyyy> <n> DE <m>
               Saldo Inicial | Cheques o Cargos | Depósitos o Abonos | Saldo Final
               <4 amounts>
    header     FECHA NUMERO SUC DESCRIPCION CHEQUES DEPOSITOS SALDO
                                            Y CARGOS Y ABONOS
    rows       the date appears only on a day's first line; '--- Saldo Dia ---' closes the day
               with the balance in SALDO
    end        'Resumen de Comisiones' (last page) or 'MENSAJES' (footer)
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import date, datetime

from .....domain.statements.model import BankStatement, DailyBalance, StatementLine, StatementSummary
from ..ocr_tabular import Table, TableError, TableSpec, norm_text
from .base import Bank, column_index, day_month, parse_clp

# The holder's own money on a Santander checking account (ADR-024): a transfer to their savings, a payment to their
# card. Shared by the PDF and the .xlsx layouts, which print the same descriptions.
SANTANDER_OWN_MONEY = (
    re.compile(r"\btransf(?:erencia)?\s+a\s+(?:cuenta\s+)?ahorro\b", re.IGNORECASE),
    re.compile(r"\bpago\s+(?:de\s+)?tarjeta\b", re.IGNORECASE),
)

_PERIOD = re.compile(r"(?P<account>\d[\d-]{6,}\d)\s+(?P<number>\d+)\s+(?P<start>\d{2}/\d{2}/\d{4})\s+(?P<end>\d{2}/\d{2}/\d{4})")
_COLUMNS = ("fecha", "numero", "suc", "descripcion", "cheques", "depositos", "saldo")


class SantanderCuentaMatica(Bank):
    code = "santander_cl_cuentamatica"
    own_money = SANTANDER_OWN_MONEY
    name = "Banco Santander Chile · CuentaMática"
    currency = "CLP"
    table = TableSpec(
        header_required=frozenset({"fecha", "descripcion", "saldo"}),
        header_tokens=frozenset({"fecha", "numero", "suc", "descripcion", "cheques", "depositos", "saldo", "y", "cargos", "abonos"}),
        stop_markers=("resumen de comisiones", "mensajes"),
    )

    def recognizes(self, first_page_text: str) -> bool:
        return "cuentamatica" in first_page_text and "santander" in first_page_text

    def parse(self, tables: Sequence[Table]) -> BankStatement:
        if not tables:
            raise TableError("no pages with a movements table")
        first = tables[0]
        account, number, start, end = self._period(first.preamble)
        summary = self._summary(first.rows[: first.header_index])

        lines: list[StatementLine] = []
        balances: list[DailyBalance] = []
        current: date | None = None
        for table in tables:
            cols = {k: column_index(table.header, k) for k in _COLUMNS}
            confs = table.data_confidences
            for r, row in enumerate(table.data):
                cell = {k: row[i].strip() for k, i in cols.items()}
                if not any(cell.values()):
                    continue
                if cell["fecha"]:
                    current = day_month(cell["fecha"], end)
                description = cell["descripcion"]
                if norm_text(description) == "saldo dia":
                    balance = parse_clp(cell["saldo"])
                    if current is None or balance is None:
                        raise TableError(f"page {table.page}: daily balance without a date or an amount")
                    balances.append(DailyBalance(current, balance))
                    continue

                charge, deposit = parse_clp(cell["cheques"]), parse_clp(cell["depositos"])
                if charge is None and deposit is None:
                    if lines and not (cell["fecha"] or cell["numero"] or cell["suc"] or cell["saldo"]):
                        # A description wrapped onto a second line.
                        lines[-1] = replace(lines[-1], description=f"{lines[-1].description} {description}")
                        continue
                    raise TableError(f"page {table.page}: row without an amount: {row!r}")
                if charge is not None and deposit is not None:
                    raise TableError(f"page {table.page}: row with both a charge and a deposit")
                if current is None:
                    raise TableError(f"page {table.page}: movement before any date")

                confidence = None
                if confs is not None:
                    confidence = min(c for c, text in zip(confs[r], row) if text.strip())
                lines.append(
                    StatementLine(
                        index=len(lines),
                        posted_on=current,
                        description=description,
                        amount=-charge if charge is not None else deposit,
                        reference=cell["numero"] or None,
                        branch=cell["suc"] or None,
                        confidence=confidence,
                        kind=self.line_kind(description),
                    )
                )
        if not lines:
            raise TableError("the statement has no movements")
        return BankStatement(
            bank=self.code,
            account_ref=account,
            currency=self.currency,
            period_start=start,
            period_end=end,
            lines=tuple(lines),
            summary=summary,
            daily_balances=tuple(balances),
            statement_number=number,
            source="ocr" if any(t.source == "ocr" for t in tables) else "text",
        )

    @staticmethod
    def _period(preamble: Sequence[str]) -> tuple[str, str, date, date]:
        for line in preamble:
            match = _PERIOD.search(line)
            if match:
                try:
                    start = datetime.strptime(match["start"], "%d/%m/%Y").date()
                    end = datetime.strptime(match["end"], "%d/%m/%Y").date()
                except ValueError as exc:
                    raise TableError(f"not a valid statement period: {match.group(0)!r}") from exc
                if start > end:
                    raise TableError("statement period ends before it starts")
                return match["account"], match["number"], start, end
        raise TableError("account and period (CARTOLA DESDE HASTA) not found")

    @staticmethod
    def _summary(preamble: Sequence[Sequence[str]]) -> StatementSummary | None:
        """From the preamble's cells (one per box), so an amount OCR split with spaces stays whole."""
        for i, row in enumerate(preamble[:-1]):
            if norm_text(" ".join(row)).startswith("saldo inicial"):
                values = [parse_clp(v) for v in preamble[i + 1] if v.strip()]
                if len(values) != 4 or any(v is None for v in values):
                    raise TableError("the summary line does not hold four amounts")
                opening, debits, credits, closing = values
                return StatementSummary(opening, debits, credits, closing)
        return None
