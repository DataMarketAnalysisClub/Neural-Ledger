"""Banco BICE, credit card 'Movimientos Nacionales / Internacionales de Tarjeta de Crédito' (.xlsx).

What the online banking exports for the current, not yet billed, period. Only the logo image names
the bank, so the layout is recognized by its wording. Layout, one sheet 'Movimientos TC':
    'Movimientos Nacionales de Tarjeta de Crédito:' (CLP) or '... Internacionales ...' (USD)
    'Nº **** **** **** Ab3x'                 the card, masked by the bank
    Inicio periodo | Total Abonos | Total Cargos     labels, values on the row below
                                               ('-120.000 CLP', '95.500 CLP'; '-12,50 US$')
    Fecha | Categoria | Detalle | Cuotas | Monto $ (or Monto US$)
    rows       newest first; dd/mm/yyyy; Monto is a number cell, positive for a charge;
               Cuotas '1 de 1' on purchases, empty on credits
    end        the first row without a date: a footnote ('* Movimientos sujetos a confirmación ...',
               'Infórmate sobre la garantía estatal ...')

The bank's own Categoria column is not used: categories come from the classifier and the user.
Unbilled movements are provisional: the next export and the billed statement repeat them, so the
statement is checked and stored but never posted (see `BankStatement.provisional`).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from .....domain.ledger.entities import AccountType
from .....domain.statements.model import BankStatement, Installment, LineKind, StatementLine, StatementSummary
from ..ocr_tabular import TableError, norm_text
from ..spreadsheet import Sheet
from .base import SheetBank, cell_money, full_date, parse_money

_CUOTAS = re.compile(r"^(\d{1,2}) de (\d{1,2})$")
_DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_FEES = ("comision", "interes", "impuesto")


class BiceTarjetaMovimientos(SheetBank):
    code = "bice_cl_tarjeta_movimientos_xlsx"
    name = "Banco BICE · Tarjeta de crédito, movimientos no facturados (Excel)"
    account_type = AccountType.CREDIT_CARD

    def recognizes(self, first_page_text: str) -> bool:
        return (
            re.search(r"movimientos (nacionales|internacionales) de tarjeta de credito", first_page_text) is not None
            and "inicio periodo" in first_page_text
            and "total cargos" in first_page_text
        )

    def parse(self, sheets: Sequence[Sheet]) -> BankStatement:
        sheet = sheets[0]
        international = "movimientos internacionales de tarjeta de credito" in norm_text(sheet.text)
        currency, decimals = ("USD", 2) if international else ("CLP", 0)

        start_text = sheet.below("Inicio periodo")
        if not start_text:
            raise TableError("'Inicio periodo' not found")
        start = full_date(start_text)
        credits, debits = parse_money(sheet.below("Total Abonos") or "", decimals), parse_money(sheet.below("Total Cargos") or "", decimals)
        if credits is None or debits is None:
            raise TableError("'Total Abonos' / 'Total Cargos' not found")

        header_at = sheet.find("Fecha")
        if header_at is None:
            raise TableError("movements header (Fecha | Detalle | Monto) not found")
        r0 = header_at[0]
        header = [norm_text(c) for c in sheet.rows[r0]]
        cols = {key: next((i for i, c in enumerate(header) if c.startswith(key)), None) for key in ("fecha", "detalle", "cuotas", "monto")}
        if cols["fecha"] is None or cols["detalle"] is None or cols["monto"] is None:
            raise TableError(f"columns Fecha, Detalle and Monto not all found in {sheet.rows[r0]!r}")

        rows = []
        for row in sheet.rows[r0 + 1 :]:
            cell = {k: (row[i].strip() if i is not None and i < len(row) else "") for k, i in cols.items()}
            if not _DATE.match(cell["fecha"]):
                if cell["monto"]:
                    raise TableError(f"row with an amount but no date: {row!r}")
                break  # a footnote ends the table
            if not cell["monto"]:
                raise TableError(f"row without an amount: {row!r}")
            bank_amount = cell_money(cell["monto"], decimals)  # positive = charge, the bank's view
            rows.append((full_date(cell["fecha"]), cell["detalle"], bank_amount, cell["cuotas"]))
        if not rows:
            raise TableError("the export has no movements")

        lines = []
        for on, description, bank_amount, cuotas in sorted(rows, key=lambda r: r[0]):  # oldest first, stable
            lines.append(
                StatementLine(
                    index=len(lines),
                    posted_on=on,
                    description=description,
                    amount=-bank_amount,
                    kind=_kind(description, bank_amount),
                    installment=_installment(cuotas),
                )
            )
        return BankStatement(
            bank=self.code,
            account_ref=_card(sheet),
            currency=currency,
            period_start=start,
            period_end=max(line.posted_on for line in lines),  # unbilled: the period is still open
            lines=tuple(lines),
            summary=StatementSummary(None, debits, -credits, None),
            source="xlsx",
            account_type=self.account_type,
            provisional=True,
        )


def _kind(description: str, bank_amount: int) -> LineKind:
    text = norm_text(description)
    if bank_amount < 0:
        return LineKind.PAYMENT if "monto cancelado" in text or text.startswith("pago") else LineKind.REFUND
    return LineKind.FEE if any(word in text for word in _FEES) else LineKind.PURCHASE


def _installment(cuotas: str) -> Installment | None:
    if not cuotas:
        return None
    match = _CUOTAS.match(cuotas)
    if not match:
        raise TableError(f"not a cuota count: {cuotas!r}")
    try:
        return Installment(int(match.group(1)), int(match.group(2)))
    except ValueError as exc:
        raise TableError(f"not a cuota count: {cuotas!r}") from exc


def _card(sheet: Sheet) -> str:
    for row in sheet.rows:
        for cell in row:
            match = re.match(r"^N[º°o]\s*((?:\*{4}\s*)+)(\w{4})$", cell.strip())
            if match:
                return f"****{match.group(2)}"
    raise TableError("card number (Nº **** ...) not found")
