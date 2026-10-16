"""Chilean credit card statement ('Estado de cuenta de tarjeta de crédito'), PDF.

Chilean issuers print card statements in one standard structure (sections I–IV; the amount to pay
built as A+B+C+D+E+F+G), so this layout is written against that structure rather than one bank.
Only Banco Edwards' version has been seen; another issuer that words a line differently fails
reconciliation (a section that does not add up) rather than being misread.

One file holds a national statement (CLP) and, after it, an international one (USD); each starts
on a page titled 'ESTADO DE CUENTA NACIONAL / INTERNACIONAL DE TARJETA DE CRÉDITO'.

National, as lines of text:
    PERÍODO FACTURADO dd/mm/yyyy dd/mm/yyyy · PAGAR HASTA dd/mm/yyyy · CUPO TOTAL $ a $ b $ c
    MONTO FACTURADO A PAGAR (PERÍODO ANTERIOR) A $ x            the opening debt
    [LUGAR] dd/mm/yy <código> <descripción> $ <monto op.> $ <total> NN/NN $ <cuota del mes>
    TOTAL <name> <letter> $ x                                    closes the lines above it:
        B payments · C automatic charges (PAT) · D one-cuota purchases · E cuotas (TASA INT. r%) ·
        F voluntary products · G charges, commissions, taxes and credits
    MONTO TOTAL FACTURADO A PAGAR (A+B+C+D+E+F+G) $ x           the closing debt
    MONTO MÍNIMO A PAGAR $ x
    VENCIMIENTO PRÓXIMOS 4 MESES: ACTUAL <MES> <MES> <MES> <MES> / $ a $ b $ c $ d $ e
International: SALDO ANTERIOR FACTURADO, PERIODO FACTURADO DESDE/HASTA, DEUDA TOTAL; a 'TOTAL DE
PAGOS' / 'TOTAL DE COMPRAS' header above its lines: <ref> [<ref. internacional>] dd/mm/yy
<descripción> <PAÍS> <monto origen> <monto US$>.

Signs become the holder's: a purchase is negative, a payment positive, and the debt (opening and
closing balance) negative. The line amount is what this statement bills: for a purchase in cuotas,
this month's cuota, dated at the statement's end (the purchase date is kept in its Installment).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from .....domain.ledger.entities import AccountType
from .....domain.shared.month import Month
from .....domain.statements.model import (
    BankStatement,
    CardObligations,
    Installment,
    LineKind,
    ScheduledAmount,
    SectionTotal,
    StatementLine,
    StatementSummary,
)
from ..ocr_tabular import Page, TableError
from .base import Bank, full_date, parse_money

_TITLE = re.compile(r"ESTADO DE CUENTA (NACIONAL|INTERNACIONAL) DE TARJETA DE CREDITO")
_CLP = r"-?[\d.]+"
_USD = r"-?[\d.]+,\d{2}"
_DATE = r"\d{2}/\d{2}/\d{4}"

_NATIONAL_LINE = re.compile(
    rf"^(?P<place>.*?)\s*(?P<date>\d{{2}}/\d{{2}}/\d{{2}}) (?P<code>\d{{6,}}) (?P<desc>.+?) "
    rf"\$ (?P<op>{_CLP}) \$ (?P<total>{_CLP}) (?P<n>\d{{2}})/(?P<of>\d{{2}}) \$ (?P<cuota>{_CLP})$"
)
_NATIONAL_TOTAL = re.compile(rf"^TOTAL .+ (?P<letter>[A-G]) \$ (?P<amount>{_CLP})$")
_RATE = re.compile(r"\s*TASA INT\. (?P<rate>\d+,\d+)%$")
_SECTION_KINDS = {"B": LineKind.PAYMENT, "C": LineKind.PURCHASE, "D": LineKind.PURCHASE, "E": LineKind.PURCHASE, "F": LineKind.PURCHASE}

_INTERNATIONAL_LINE = re.compile(
    rf"^(?P<ref>\d{{4}}) (?:(?P<intl>\d{{10,}}) )?(?P<date>\d{{2}}/\d{{2}}/\d{{2}}) (?P<desc>.+?) "
    rf"(?P<country>[A-Z]{{2}}) (?P<origin>{_USD}) (?P<usd>{_USD})$"
)
_INTERNATIONAL_SECTIONS = (
    (re.compile(rf"^TOTAL DE PAGOS US\$ (?P<amount>{_USD})$"), "PAGOS"),
    (re.compile(rf"^TOTAL DE COMPRAS US\$ (?P<amount>{_USD})$"), "COMPRAS"),
    (re.compile(rf"^COMISIONES, OTROS CARGOS Y ABONOS A LA CUENTA US\$ (?P<amount>{_USD})$"), "CARGOS"),
)

_MONTHS = ("ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE")


class ChileanCardStatement(Bank):
    code = "cl_tarjeta_credito_pdf"
    name = "Estado de cuenta de tarjeta de crédito (formato chileno A–G; visto en Banco Edwards)"
    account_type = AccountType.CREDIT_CARD

    def recognizes(self, first_page_text: str) -> bool:
        return (
            re.search(r"estado de cuenta (nacional|internacional) de tarjeta de credito", first_page_text) is not None
            and "periodo facturado" in first_page_text
        )

    def read(self, pages: Sequence[Page]) -> tuple[BankStatement, ...]:
        documents: list[tuple[str, list[str], str]] = []  # (kind, lines, source)
        for page in pages:
            # Descriptions keep their case and accents; labels are matched on `_plain` text.
            lines = [unicodedata.normalize("NFC", line).strip() for line in page.text.splitlines() if line.strip()]
            title = next((m for m in (_TITLE.search(_plain(line)) for line in lines[:6]) if m), None)
            if title:
                documents.append((title.group(1), [], page.source))
            elif not documents:
                raise TableError(f"page {page.number}: a card statement page before any statement title")
            documents[-1][1].extend(lines)
        statements = []
        for kind, lines, source in documents:
            read = self._national if kind == "NACIONAL" else self._international
            statements.append(read(lines, "ocr" if source == "ocr" else "text"))
        if not statements:
            raise TableError("no card statement found")
        return tuple(statements)

    # ------------------------------------------------------------------ national (CLP)
    def _national(self, lines: list[str], source: str) -> BankStatement:
        start, end = _dates(lines, rf"PERIODO FACTURADO ({_DATE}) ({_DATE})", "PERIODO FACTURADO")
        if start > end:
            raise TableError("statement period ends before it starts")
        previous = _money_after(lines, rf"MONTO FACTURADO A PAGAR \(PERIODO ANTERIOR\) A \$ ({_CLP})", 0)
        total = _money_after(lines, rf"MONTO TOTAL FACTURADO A PAGAR \(.*?\) \$ ({_CLP})", 0)
        minimum = _optional_money(lines, rf"^MONTO MINIMO A PAGAR \$ ({_CLP})$", 0)
        limit = _limits(lines, rf"^CUPO TOTAL \$ ({_CLP}) \$ ({_CLP}) \$ ({_CLP})$", 0)

        statement_lines: list[StatementLine] = []
        pending: list[re.Match[str]] = []
        sections: list[SectionTotal] = []
        for line in lines:
            if match := _NATIONAL_LINE.match(line):
                pending.append(match)
            elif total_match := _NATIONAL_TOTAL.match(_plain(line)):
                letter = total_match.group("letter")
                sections.append(SectionTotal(letter, -_clp(total_match.group("amount"))))
                for m in pending:
                    statement_lines.append(self._national_line(m, letter, len(statement_lines), end))
                pending = []
        if pending:
            raise TableError(f"{len(pending)} movements after the last printed subtotal")
        if not statement_lines:
            raise TableError("the statement has no movements")

        return BankStatement(
            bank=self.code,
            account_ref=_card(lines),
            currency="CLP",
            period_start=start,
            period_end=end,
            lines=tuple(statement_lines),
            summary=StatementSummary(-previous, None, None, -total),
            source=source,
            account_type=self.account_type,
            section_totals=tuple(sections),
            obligations=CardObligations(
                amount_due=total,
                minimum_due=minimum,
                due_date=_due(lines),
                credit_limit=limit[0],
                credit_used=limit[1],
                credit_available=limit[2],
                upcoming=_upcoming(lines, end),
            ),
        )

    @staticmethod
    def _national_line(m: re.Match[str], section: str, index: int, period_end: date) -> StatementLine:
        bank_amount = _clp(m.group("cuota"))  # positive = charge, the bank's view
        kind = _SECTION_KINDS.get(section) or (LineKind.REFUND if bank_amount < 0 else LineKind.FEE)
        number, of = int(m.group("n")), int(m.group("of"))
        if not 1 <= number <= of:
            raise TableError(f"not a cuota: {m.group('n')}/{m.group('of')}")
        description, rate = m.group("desc"), None
        if rate_match := _RATE.search(description):
            description = description[: rate_match.start()]
            rate = Decimal(rate_match.group("rate").replace(",", ".")) / 100
        purchased_on = full_date(m.group("date"))
        installment = None
        if of > 1:
            installment = Installment(number, of, _clp(m.group("op")), rate, purchased_on)
        return StatementLine(
            index=index,
            # A cuota of an older purchase is billed now: it belongs to this statement's period.
            posted_on=period_end if installment else purchased_on,
            description=description.strip(),
            amount=-bank_amount,
            reference=m.group("code"),
            branch=m.group("place").strip() or None,
            kind=kind,
            section=section,
            installment=installment,
        )

    # ------------------------------------------------------------------ international (USD)
    def _international(self, lines: list[str], source: str) -> BankStatement:
        (start,) = _dates(lines, rf"PERIODO FACTURADO DESDE ({_DATE})", "PERIODO FACTURADO DESDE")
        (end,) = _dates(lines, rf"PERIODO FACTURADO HASTA ({_DATE})", "PERIODO FACTURADO HASTA")
        if start > end:
            raise TableError("statement period ends before it starts")
        previous = _money_after(lines, rf"SALDO ANTERIOR FACTURADO US\$ ({_USD})", 2)
        debt = _money_after(lines, rf"DEUDA TOTAL US\$ ({_USD})", 2)
        limit = _limits(lines, rf"^CUPO TOTAL US\$ ({_USD}) US\$ ({_USD}) US\$ ({_USD})$", 2)

        statement_lines: list[StatementLine] = []
        sections: list[SectionTotal] = []
        current: str | None = None
        for line in lines:
            header = next(((name, m) for pattern, name in _INTERNATIONAL_SECTIONS if (m := pattern.match(_plain(line)))), None)
            if header:
                current = header[0]
                sections.append(SectionTotal(current, -_usd(header[1].group("amount"))))
            elif _plain(line).startswith("TOTAL TARJETA"):
                current = None
            elif (m := _INTERNATIONAL_LINE.match(line)) and current:
                bank_amount = _usd(m.group("usd"))
                kind = {"PAGOS": LineKind.PAYMENT, "COMPRAS": LineKind.PURCHASE}.get(current) or (
                    LineKind.REFUND if bank_amount < 0 else LineKind.FEE
                )
                statement_lines.append(
                    StatementLine(
                        index=len(statement_lines),
                        posted_on=full_date(m.group("date")),
                        description=m.group("desc").strip(),
                        amount=-bank_amount,
                        reference=m.group("intl") or m.group("ref"),
                        branch=m.group("country"),
                        kind=kind,
                        section=current,
                    )
                )
        if not statement_lines:
            raise TableError("the international statement has no movements")
        return BankStatement(
            bank=self.code,
            account_ref=_card(lines),
            currency="USD",
            period_start=start,
            period_end=end,
            lines=tuple(statement_lines),
            summary=StatementSummary(-previous, None, None, -debt),
            source=source,
            account_type=self.account_type,
            section_totals=tuple(sections),
            obligations=CardObligations(
                amount_due=debt,
                minimum_due=None,  # not printed on the international statement
                due_date=_due(lines),
                credit_limit=limit[0],
                credit_used=limit[1],
                credit_available=limit[2],
            ),
        )


def _plain(line: str) -> str:
    """Accents off and uppercase, punctuation kept: the label patterns are written against this."""
    decomposed = unicodedata.normalize("NFD", line)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn").upper().strip()


def _clp(text: str) -> int:
    value = parse_money(text, 0)
    if value is None:
        raise TableError(f"not an amount: {text!r}")
    return value


def _usd(text: str) -> int:
    value = parse_money(text, 2)
    if value is None:
        raise TableError(f"not an amount: {text!r}")
    return value


def _search(lines: Sequence[str], pattern: str) -> re.Match[str] | None:
    """The first line whose `_plain` text matches a label pattern."""
    compiled = re.compile(pattern)
    return next((m for m in (compiled.search(_plain(line)) for line in lines) if m), None)


def _dates(lines: Sequence[str], pattern: str, what: str) -> tuple[date, ...]:
    match = _search(lines, pattern)
    if not match:
        raise TableError(f"{what} not found")
    return tuple(full_date(g) for g in match.groups())


def _money_after(lines: Sequence[str], pattern: str, decimals: int) -> int:
    value = _optional_money(lines, pattern, decimals)
    if value is None:
        raise TableError(f"not found: {pattern}")
    return value


def _optional_money(lines: Sequence[str], pattern: str, decimals: int) -> int | None:
    match = _search(lines, pattern)
    return parse_money(match.group(1), decimals) if match else None


def _limits(lines: Sequence[str], pattern: str, decimals: int) -> tuple[int | None, int | None, int | None]:
    match = _search(lines, pattern)
    if not match:
        return (None, None, None)
    total, used, available = (parse_money(g, decimals) for g in match.groups())
    return total, used, available


def _due(lines: Sequence[str]) -> date | None:
    match = _search(lines, rf"PAGAR HASTA ({_DATE})")
    return full_date(match.group(1)) if match else None


def _card(lines: Sequence[str]) -> str:
    match = _search(lines, r"N° DE TARJETA DE CREDITO .*?(\d{4})$")
    if not match:
        raise TableError("card number (N° DE TARJETA DE CRÉDITO) not found")
    return f"****{match.group(1)}"


def _upcoming(lines: Sequence[str], period_end: date) -> tuple[ScheduledAmount, ...]:
    """'VENCIMIENTO PRÓXIMOS 4 MESES': the cuotas the next four statements will bill, as printed.

    The month names must be the four months after the statement's; the amounts row is the next
    line with five '$ x' amounts ('ACTUAL' first, which is not used). A chart label printed on the
    same lines is ignored. Not found → () (nothing printed to check).
    """
    for i, line in enumerate(map(_plain, lines)):
        header = re.match(r"^ACTUAL ((?:[A-Z]+ ){3}[A-Z]+)\b", line)
        if not header:
            continue
        names = header.group(1).split()
        expected = [Month.of(period_end).plus(k) for k in range(1, 5)]
        if names != [_MONTHS[m.month - 1] for m in expected]:
            raise TableError(f"upcoming months {names} are not the four after {period_end:%m/%Y}")
        for following in lines[i + 1 : i + 4]:
            amounts = re.findall(rf"\$ ({_CLP})", following)
            if len(amounts) >= 5:
                return tuple(ScheduledAmount(month, _clp(a)) for month, a in zip(expected, amounts[1:5]))
        raise TableError("the upcoming cuotas row was not found under its months")
    return ()
