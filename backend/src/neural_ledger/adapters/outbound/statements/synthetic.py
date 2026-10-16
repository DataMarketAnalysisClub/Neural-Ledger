"""Synthetic cartolas: random bank exports that add up, for demos and manual testing. Standard library only.

Each file uses a layout the readers in `banks/` already accept, so importing it runs the real path
(read → redact → reconcile → store → post → audit) exactly as for a downloaded statement:

    Santander 'Cartola de cuenta Corriente' (.xlsx)   checking account; reconciles, so it is posted to the ledger
    BICE 'Movimientos Nacionales de Tarjeta de Crédito' (.xlsx)   unbilled card movements; stored, never posted

Merchants are businesses from the classifier's training vocabulary, so most charges get a category.
The holder, RUT, email and account numbers are fictional, and redaction masks them at import anyway.
All randomness comes from the `random.Random` passed in: the same seed gives the same bytes.
"""

from __future__ import annotations

import calendar
import io
import random
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from xml.sax.saxutils import escape

# Fictional on purpose. The repository is public: never put a real person's data here.
HOLDER = "CLIENTE SINTETICO"
HOLDER_RUT = "11.111.111-1"
HOLDER_EMAIL = "cliente.sintetico@example.com"
EMPLOYER = "EMPRESA SINTETICA SPA"

MONTHS_ES = ("Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre")


@dataclass(frozen=True, slots=True)
class Merchant:
    text: str  # as the bank prints it
    category: str  # what the classifier should answer; only used for the card export's bank column
    low: int  # CLP, inclusive
    high: int


# Variable spend: (merchant, how many times a month: min, max). Amounts are drawn per purchase.
VARIABLE: tuple[tuple[Merchant, int, int], ...] = (
    (Merchant("COMPRA LIDER EXPRESS", "groceries", 6_000, 45_000), 2, 4),
    (Merchant("COMPRA TDB UNIMARC", "groceries", 5_000, 35_000), 1, 3),
    (Merchant("COMPRA SANTA ISABEL", "groceries", 8_000, 60_000), 1, 3),
    (Merchant("COMPRA TDB JUMBO CONCEPCION", "groceries", 25_000, 90_000), 0, 2),
    (Merchant("STARBUCKS COFFEE CENTRO", "dining", 3_500, 9_000), 1, 4),
    (Merchant("UBER EATS PEDIDO", "dining", 9_000, 25_000), 1, 3),
    (Merchant("PEDIDOSYA TICKET", "dining", 8_000, 22_000), 0, 3),
    (Merchant("RENDIBU BARROS ARANA", "dining", 6_000, 15_000), 0, 2),
    (Merchant("UBER TRIP HELP.UBER.COM", "transport", 3_000, 14_000), 2, 5),
    (Merchant("COPEC ESTACION DE SERVICIO", "transport", 20_000, 45_000), 0, 2),
    (Merchant("EFE SUR BIOTREN", "transport", 800, 1_600), 2, 6),
    (Merchant("FARMACIAS CRUZ VERDE", "health", 4_000, 30_000), 0, 2),
    (Merchant("SALCOBRAND S.A.", "health", 3_500, 25_000), 0, 1),
    (Merchant("MERCADO LIBRE COMPRA", "shopping", 9_000, 70_000), 0, 2),
    (Merchant("FALABELLA RETAIL", "shopping", 15_000, 90_000), 0, 1),
    (Merchant("SODIMAC HOMECENTER", "shopping", 8_000, 60_000), 0, 1),
    (Merchant("CINEMARK MALL PLAZA", "entertainment", 5_000, 14_000), 0, 1),
)

# Fixed bills: (merchant, day of the month). The amount is drawn once per history, then varies a little.
BILLS: tuple[tuple[Merchant, int], ...] = (
    (Merchant("ENTEL S.A. PLAN MOVIL", "utilities", 14_990, 24_990), 5),
    (Merchant("MUNDO PACIFICO INTERNET", "utilities", 19_990, 29_990), 8),
    (Merchant("PAGO CGE DISTRIBUCION", "utilities", 22_000, 55_000), 12),
    (Merchant("PAGO EN LINEA ESSBIO", "utilities", 11_000, 24_000), 14),
    (Merchant("CARGO MENSUAL NETFLIX", "entertainment", 7_990, 12_990), 18),
    (Merchant("CARGO AUTOMATICO SPOTIFY", "entertainment", 4_990, 6_990), 21),
)

# The card export prints the bank's own category; the importer ignores it (categories come from the classifier).
_BANK_CATEGORY = {
    "groceries": "Supermercados",
    "dining": "Restaurantes",
    "transport": "Transporte",
    "health": "Salud",
    "shopping": "Shopping",
    "utilities": "Hogar",
    "entertainment": "Entretenimiento",
}


@dataclass(frozen=True, slots=True)
class CheckingCartola:
    """One month of a checking account, and the numbers a caller needs to chain the next month."""

    content: bytes  # the .xlsx file
    month: date  # first day of the statement's month
    opening: int
    closing: int
    movements: int


@dataclass(frozen=True, slots=True)
class CardExport:
    content: bytes  # the .xlsx file
    start: date
    end: date
    movements: int


@dataclass(frozen=True, slots=True)
class Household:
    """What stays the same from month to month: the account, the salary and the bills."""

    account: str
    salary: int
    rent: int  # paid by transfer on the 5th
    bills: tuple[tuple[Merchant, int, int], ...]  # (merchant, day, base amount)
    savings_rate_pct: int

    @classmethod
    def random(cls, rng: random.Random, salary: int | None = None) -> Household:
        account = f"0-000-{rng.randrange(10, 100)}-{rng.randrange(10_000, 100_000)}-{rng.randrange(10)}"
        salary = salary or _round(rng.randint(1_100_000, 1_900_000), 10_000)
        rent = _round(salary * rng.randint(28, 35) // 100, 10_000)
        bills = tuple((m, day, _round(rng.randint(m.low, m.high), 10)) for m, day in BILLS)
        return cls(account, salary, rent, bills, rng.choice((5, 8, 10)))


def checking_cartola(rng: random.Random, household: Household, month: date, opening: int, number: int = 1) -> CheckingCartola:
    """A Santander checking-account cartola for `month`: salary on the last weekday, bills, daily spending.

    Charges that would take the balance below zero are left out, so the account never overdraws.
    Totals, the closing balance and every daily balance are computed from the movements, so the
    statement reconciles and the importer marks it verified.
    """
    first = month.replace(day=1)
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    payday = _last_weekday(last)

    planned: list[tuple[int, str, int, bool]] = []  # (day, description, signed amount, is a purchase)
    planned.append((5, f"{rng.randrange(10**9):010d} TRANSFERENCIA A TERCEROS ARRIENDO", -household.rent, False))
    for merchant, day, base in household.bills:
        amount = base if merchant.category == "entertainment" else _round(base * rng.randint(85, 120) // 100, 10)
        planned.append((min(day, last.day), merchant.text, -amount, False))
    for merchant, low, high in VARIABLE:
        for _ in range(rng.randint(low, high)):
            planned.append((rng.randint(1, last.day), f"Compra Nacional VD {merchant.text}", -_round(rng.randint(merchant.low, merchant.high), 10), True))
    for _ in range(rng.randint(0, 2)):
        planned.append((rng.randint(1, last.day), "*/Giro Nacional VD", -rng.choice((20_000, 40_000, 60_000)), False))
    planned.append((payday.day, f"{rng.randrange(10**9):010d} REMUNERACION {EMPLOYER}", household.salary, False))
    savings = _round(household.salary * household.savings_rate_pct // 100, 1_000)
    # Not 'Transf a Cuenta Ahorro': the classifier reads that as groceries at 0.50, which passes its confidence floor.
    planned.append((payday.day, f"{rng.randrange(10**9):010d} Transf a Ahorro", -savings, False))

    # Within a day: deposits first, then charges in the drawn order. The sort is stable.
    planned.sort(key=lambda p: (p[0], p[2] < 0))
    balance = opening
    movements: list[tuple[str, str, str, str, int]] = []  # (dd/mm, branch, description, document, signed amount)
    for day, description, amount, purchase in planned:
        if balance + amount < 0:
            continue
        balance += amount
        document = f"{rng.randrange(1_000_000, 10_000_000)}" if purchase else ""
        movements.append((f"{day:02d}/{first.month:02d}", rng.choice(("Sucursal Centro", "Sucursal Mall", "O.Gerencia")), description, document, amount))
    content = _santander_xlsx(household.account, number, first, last, opening, movements)
    return CheckingCartola(content, first, opening, balance, len(movements))


def checking_history(rng: random.Random, household: Household, last_month: date, months: int, opening: int) -> list[CheckingCartola]:
    """`months` consecutive cartolas ending with `last_month`, each opening where the previous one closed."""
    if months < 1:
        raise ValueError("months must be at least 1")
    cartolas = []
    first = _add_months(last_month.replace(day=1), -(months - 1))
    balance = opening
    for k in range(months):
        cartola = checking_cartola(rng, household, _add_months(first, k), balance, number=k + 1)
        cartolas.append(cartola)
        balance = cartola.closing
    return cartolas


def card_export(rng: random.Random, start: date, end: date, previous_bill: int | None = None) -> CardExport:
    """A BICE national card export of the unbilled movements from `start` to `end`.

    Purchases are '1 de 1', with up to two in cuotas ('1 de 3', '1 de 6': this month's cuota is the amount);
    the previous bill is paid ('MONTO CANCELADO') and there may be a refund. Newest first, like the bank.
    """
    if end < start:
        raise ValueError("the period ends before it starts")
    days = (end - start).days
    rows: list[tuple[date, str, str, str, int]] = []  # (date, bank category, detail, cuotas, bank-signed amount)
    for merchant, low, high in VARIABLE:
        for _ in range(max(0, rng.randint(low, high) - 1)):
            on = start + timedelta(days=rng.randint(0, days))
            rows.append((on, _BANK_CATEGORY[merchant.category], f"{merchant.text} COMPRAS", "1 de 1", _round(rng.randint(merchant.low, merchant.high), 10)))
    for merchant in rng.sample([m for m, _, _ in VARIABLE if m.category == "shopping"], rng.randint(0, 2)):
        total = rng.choice((3, 6))
        cuota = _round(rng.randint(merchant.low, merchant.high) * 2 // total, 10)
        rows.append((start + timedelta(days=rng.randint(0, days)), _BANK_CATEGORY[merchant.category], f"{merchant.text} COMPRAS", f"1 de {total}", cuota))
    paid = previous_bill if previous_bill is not None else _round(rng.randint(150_000, 450_000), 10)
    rows.append((start + timedelta(days=min(days, rng.randint(5, 12))), "Abonos", "MONTO CANCELADO", "", -paid))
    if rows and rng.random() < 0.4:
        refunded = rng.choice([r for r in rows if r[4] > 0] or rows)
        rows.append((refunded[0], "Abonos", refunded[2].replace(" COMPRAS", " REVCOMPRAS"), "", -_round(refunded[4] // 2, 10)))
    rows.sort(key=lambda r: r[0], reverse=True)
    content = _bice_xlsx(start, f"{rng.choice('ABCDEFGHJK')}{rng.randrange(10)}{rng.choice('abcdefghjk')}{rng.randrange(10)}", rows)
    return CardExport(content, start, end, len(rows))


@dataclass(frozen=True, slots=True)
class SampleFile:
    name: str  # a file name that says what it is: bank, account kind, month, seed
    content: bytes
    description: str  # one line for the terminal


class SyntheticStatements:
    """What the CLI's `cartola` and `seed` commands call (wired in bootstrap). One seed, reproducible files."""

    def checking(self, seed: int, last_month: date, months: int = 1, opening: int | None = None, salary: int | None = None) -> list[SampleFile]:
        """`opening` defaults to one salary: the first month starts as if last month's pay just arrived."""
        rng = random.Random(seed)
        household = Household.random(rng, salary)
        files = []
        for c in checking_history(rng, household, last_month, months, household.salary if opening is None else opening):
            name = f"santander-cuenta-corriente-{c.month:%Y-%m}-seed{seed}.xlsx"
            files.append(SampleFile(name, c.content, f"checking {c.month:%Y-%m}: {c.movements} movements, balance {c.opening:,} → {c.closing:,} CLP"))
        return files

    def card(self, seed: int, start: date, end: date) -> SampleFile:
        export = card_export(random.Random(f"card-{seed}"), start, end)
        name = f"bice-tarjeta-no-facturado-{end:%Y-%m}-seed{seed}.xlsx"
        return SampleFile(name, export.content, f"credit card {start} → {end}: {export.movements} unbilled movements")


# ---------------------------------------------------------------------------------------------
# Layouts. Keep them in step with the readers: banks/santander_xlsx.py and banks/bice_xlsx.py.
# ---------------------------------------------------------------------------------------------
Cell = str | int | float | None


def _santander_xlsx(account: str, number: int, first: date, last: date, opening: int, movements: Sequence[tuple[str, str, str, str, int]]) -> bytes:
    debits = -sum(m[4] for m in movements if m[4] < 0)
    credits = sum(m[4] for m in movements if m[4] > 0)
    rows: list[list[Cell]] = [
        ["Banco Santander", None, "", "", f"Cartola de cuenta Corriente - {MONTHS_ES[first.month - 1]} {first.year}"],
        ["Sr(a)", HOLDER, "", "", "Cartola N°", str(number), ""],
        ["Rut", HOLDER_RUT, "", "", "Desde", first.strftime("%d/%m/%Y"), ""],
        ["E-mail", HOLDER_EMAIL, "", "", "Hasta", last.strftime("%d/%m/%Y"), ""],
        ["INFORMACIÓN CUENTA CORRIENTE"],
        ["Tipo de Cuenta:", "CTA CTE", "", "", "N° Cuenta:", account, ""],
        ["Saldo inicial:", _pesos(opening), "", "", "Impuestos:", "$0", ""],
        ["Saldo final:", _pesos(opening - debits + credits), "", "", "Depósitos:", "$0", ""],
        ["Otros abonos:", _pesos(credits), "", "", "Cheques:", "$0", ""],
        ["Otros cargos:", _pesos(debits), "", "", "Comisiones:", "", ""],
        ["DETALLE DE MOVIMIENTOS", None, None, None, None, "SALDOS DIARIOS"],
        ["FECHA", "SUCURSAL", "DESCRIPCIÓN", "N° DOCUMENTO", "CHEQUES Y OTROS CARGOS", "DEPOSITOS Y OTROS ABONOS", "SALDO"],
    ]
    balance = opening
    for i, (day, branch, description, document, amount) in enumerate(movements):
        balance += amount
        last_of_day = i == len(movements) - 1 or movements[i + 1][0] != day
        rows.append([day, branch, description, document, -amount if amount < 0 else None, amount if amount > 0 else None, balance if last_of_day else None])
    rows += [["", "", "Resumen de Comisiones"], ["", "", "SIN COMISIONES EN EL PERIODO"], ["MENSAJES"]]
    return write_xlsx(rows, "Cartola de Cuenta")


def _bice_xlsx(start: date, card_suffix: str, rows: Sequence[tuple[date, str, str, str, int]]) -> bytes:
    abonos = -sum(r[4] for r in rows if r[4] < 0)
    cargos = sum(r[4] for r in rows if r[4] > 0)
    sheet: list[list[Cell]] = [
        [],
        [None, None, None, None, "Movimientos Nacionales de Tarjeta de Crédito:"],
        [None, None, None, None, f"Nº **** **** **** {card_suffix}"],
        [None, "Inicio periodo", None, None, "Total Abonos", "Total Cargos"],
        [None, start.strftime("%d/%m/%Y"), None, None, f"-{_dots(abonos)}\xa0CLP", f"{_dots(cargos)}\xa0CLP"],
        [None, "Fecha", "Categoria", "Detalle", None, None, None, None, "Cuotas", "Monto $"],
    ]
    for on, category, detail, cuotas, amount in rows:
        sheet.append([None, on.strftime("%d/%m/%Y"), category, detail, None, None, None, None, cuotas, amount])
    sheet.append([None, "* Movimientos sujetos a confirmación por los comercios respectivos."])
    sheet.append([None, "Infórmate sobre la garantía estatal de los depósitos en tu banco o en www.cmfchile.cl"])
    return write_xlsx(sheet, "Movimientos TC")


def write_xlsx(rows: Sequence[Sequence[Cell]], sheet_name: str = "Hoja1", shared: bool = True) -> bytes:
    """A minimal valid .xlsx with one sheet. Strings go to sharedStrings (or inline with shared=False); numbers stay numbers."""
    strings: list[str] = []
    rows_xml = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            if value is None or value == "":
                continue
            ref = f"{_column(c)}{r}"
            if isinstance(value, str):
                if shared:
                    strings.append(value)
                    cells.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
                else:
                    cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
            else:
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
        rows_xml.append(f'<row r="{r}">{"".join(cells)}</row>')
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    parts = {
        "[Content_Types].xml": '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        "xl/workbook.xml": f'<?xml version="1.0"?><workbook xmlns="{main}" xmlns:r="{rel}"><sheets><sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId4"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId4" Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": f'<?xml version="1.0"?><worksheet xmlns="{main}"><sheetData>{"".join(rows_xml)}</sheetData></worksheet>',
    }
    if shared:
        items = "".join(f"<si><t>{escape(s)}</t></si>" for s in strings)
        parts["xl/sharedStrings.xml"] = f'<?xml version="1.0"?><sst xmlns="{main}">{items}</sst>'
    buffer = io.BytesIO()
    # A fixed timestamp on every entry, so the same rows always give the same bytes.
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in parts.items():
            archive.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), body, compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


def _column(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def _dots(amount: int) -> str:
    return f"{amount:,}".replace(",", ".")


def _pesos(amount: int) -> str:
    return f"${_dots(amount)}"


def _round(amount: int, step: int) -> int:
    return max(step, amount // step * step)


def _last_weekday(day: date) -> date:
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _add_months(first: date, k: int) -> date:
    index = first.year * 12 + first.month - 1 + k
    return date(index // 12, index % 12 + 1, 1)
