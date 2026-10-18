"""Banco Santander Chile, 'Cartola de cuenta Corriente' exported as Excel (.xlsx).

Layout, one sheet:
    A1 'Banco Santander', E1 'Cartola de cuenta Corriente - <Mes> <Año>'
    label/value pairs   Cartola N° · Desde · Hasta · N° Cuenta · Saldo inicial · Saldo final ·
                        Otros abonos · Depósitos · Otros cargos · Cheques · Impuestos · Comisiones
                        (printed as '$100.000'; an empty value is zero)
    'DETALLE DE MOVIMIENTOS', then the header
        FECHA | SUCURSAL | DESCRIPCIÓN | N° DOCUMENTO | CHEQUES Y OTROS CARGOS | DEPOSITOS Y OTROS ABONOS | SALDO
    rows       every row has its date (dd/mm); amounts are number cells; SALDO is filled on a day's
               last row only, and is that day's closing balance
    end        the first row without a date ('Resumen de Comisiones', 'MENSAJES')
"""

from __future__ import annotations

from collections.abc import Sequence

from .....domain.statements.model import BankStatement, DailyBalance, StatementLine, StatementSummary
from ..ocr_tabular import TableError, norm_text
from ..spreadsheet import Sheet
from .base import SheetBank, cell_money, day_month, full_date, parse_money
from .santander import SANTANDER_OWN_MONEY

# Each column by the first word of its header, normalized.
_COLUMNS = {"fecha": "fecha", "sucursal": "sucursal", "descripcion": "descripcion", "documento": "n documento", "cargos": "cheques", "abonos": "depositos", "saldo": "saldo"}


class SantanderCuentaCorrienteXlsx(SheetBank):
    code = "santander_cl_cuentacorriente_xlsx"
    own_money = SANTANDER_OWN_MONEY
    name = "Banco Santander Chile · Cuenta corriente (Excel)"
    currency = "CLP"

    def recognizes(self, first_page_text: str) -> bool:
        return first_page_text.startswith("banco santander") and "cartola de cuenta corriente" in first_page_text and "detalle de movimientos" in first_page_text

    def parse(self, sheets: Sequence[Sheet]) -> BankStatement:
        sheet = sheets[0]
        start, end = full_date(_required(sheet, "Desde")), full_date(_required(sheet, "Hasta"))
        if start > end:
            raise TableError("statement period ends before it starts")
        debits = sum(_money(sheet, label) for label in ("Otros cargos:", "Cheques:", "Impuestos:", "Comisiones:"))
        credits = sum(_money(sheet, label) for label in ("Otros abonos:", "Depósitos:"))
        summary = StatementSummary(_money(sheet, "Saldo inicial:"), debits, credits, _money(sheet, "Saldo final:"))

        header_at = sheet.find("FECHA")
        if header_at is None:
            raise TableError("movements header (FECHA ...) not found")
        r0 = header_at[0]
        cols = _columns(sheet.rows[r0])
        lines: list[StatementLine] = []
        balances: list[DailyBalance] = []
        for row in sheet.rows[r0 + 1 :]:
            cell = {k: (row[i].strip() if i < len(row) else "") for k, i in cols.items()}
            if not cell["fecha"]:
                if cell["cargos"] or cell["abonos"] or cell["saldo"]:
                    raise TableError(f"row with an amount but no date: {row!r}")
                break  # the table ends at the first dateless row ('Resumen de Comisiones')
            on = day_month(cell["fecha"], end)
            charge, deposit = cell_money(cell["cargos"], 0), cell_money(cell["abonos"], 0)
            if (charge is None) == (deposit is None):
                raise TableError(f"row needs exactly one of a charge or a deposit: {row!r}")
            lines.append(
                StatementLine(
                    index=len(lines),
                    posted_on=on,
                    description=cell["descripcion"],
                    amount=-charge if charge is not None else deposit,
                    reference=cell["documento"] or None,
                    branch=cell["sucursal"] or None,
                    kind=self.line_kind(cell["descripcion"]),
                )
            )
            balance = cell_money(cell["saldo"], 0)
            if balance is not None:
                balances.append(DailyBalance(on, balance))
        if not lines:
            raise TableError("the statement has no movements")
        return BankStatement(
            bank=self.code,
            account_ref=_required(sheet, "N° Cuenta:"),
            currency=self.currency,
            period_start=start,
            period_end=end,
            lines=tuple(lines),
            summary=summary,
            daily_balances=tuple(balances),
            statement_number=sheet.right_of("Cartola N°") or None,
            source="xlsx",
            account_type=self.account_type,
        )


def _required(sheet: Sheet, label: str) -> str:
    value = sheet.right_of(label)
    if not value:
        raise TableError(f"{label!r} not found or empty")
    return value.strip()


def _money(sheet: Sheet, label: str) -> int:
    value = sheet.right_of(label)
    if value is None:
        raise TableError(f"{label!r} not found")
    return parse_money(value, 0) or 0


def _columns(header: Sequence[str]) -> dict[str, int]:
    found = {}
    for key, word in _COLUMNS.items():
        index = next((i for i, cell in enumerate(header) if norm_text(cell).startswith(word)), None)
        if index is None:
            raise TableError(f"column {word!r} not found in header {list(header)!r}")
        found[key] = index
    return found
