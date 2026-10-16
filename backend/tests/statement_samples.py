"""Synthetic cartolas for tests. The repository is public: never commit a real statement.

`santander_pdf` draws a fictional 'Estado CuentaMática' with the real layout's coordinates,
fonts and two-line header, so the whole read path (pdfplumber → rebuild → Bank) is exercised.
Totals and daily balances are computed from the movements unless a test overrides them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from neural_ledger.adapters.outbound.statements.synthetic import write_xlsx as xlsx

# (day "DD/MM", reference, branch, description, signed amount)
Movement = tuple[str, str, str, str, int]

DEFAULT_MOVEMENTS: tuple[Movement, ...] = (
    ("02/12", "2441010", "401", "Compra Nacional MD SHOP ONE", -3_280),
    ("02/12", "2441010", "401", "Compra Nacional MD CAFE TWO", -5_300),
    ("04/12", "", "90", "0000000001 PAGO PROVEEDOR X", 163_521),
    ("15/12", "", "300", "Fondo Mutuo Sistematico P", -10_000),
    ("29/12", "", "90", "0000000002 REMUNERACION Y", 300_000),
    ("29/12", "", "93", "0000000003 Transf a Ahorro", -40_000),
    ("05/01", "2731010", "401", "Compra Nacional MD MARKET", -2_500),
)


@dataclass(frozen=True)
class Sample:
    movements: tuple[Movement, ...] = DEFAULT_MOVEMENTS
    opening: int = 1_000_000
    period: tuple[str, str] = ("30/11/2025", "05/01/2026")  # crosses a year: 05/01 must be 2026
    account: str = "0-000-00-12345-6"
    rows_per_page: int = 6
    summary_override: tuple[int, int, int, int] | None = None
    daily_override: dict[str, int] = field(default_factory=dict)  # day → printed balance


def _fmt(amount: int) -> str:
    return f"{amount:,}".replace(",", ".")


def santander_pdf(sample: Sample | None = None) -> bytes:
    import pymupdf

    sample = sample or Sample()
    rows: list[tuple] = []  # ("m", day, ref, branch, desc, amount) | ("d", balance)
    balance = sample.opening
    days = [m[0] for m in sample.movements]
    for i, (day, ref, branch, desc, amount) in enumerate(sample.movements):
        rows.append(("m", day if i == 0 or days[i - 1] != day else "", ref, branch, desc, amount))
        balance += amount
        if i == len(days) - 1 or days[i + 1] != day:
            rows.append(("d", sample.daily_override.get(day, balance)))
    debits = -sum(m[4] for m in sample.movements if m[4] < 0)
    credits = sum(m[4] for m in sample.movements if m[4] > 0)
    summary = sample.summary_override or (sample.opening, debits, credits, sample.opening - debits + credits)

    chunks = [rows[k : k + sample.rows_per_page] for k in range(0, len(rows), sample.rows_per_page)]
    doc = pymupdf.open()
    for n, chunk in enumerate(chunks, start=1):
        page = doc.new_page(width=612, height=850)

        def text(x: float, top: float, s: str, font: str = "helv", size: float = 7.0, page=page) -> None:
            page.insert_text((x, top + size * 0.8), s, fontname=font, fontsize=size)

        def right(x1: float, top: float, s: str) -> None:
            text(x1 - pymupdf.get_text_length(s, fontname="cour", fontsize=8), top, s, "cour", 8)

        text(340, 19, "CUENTAMATICA", "hebo", 28)
        text(36, 76, "PEREZ . ANA", size=9)
        text(36, 164, "ESTADO CUENTAMATICA", "hebo", 9)
        for x, s in ((360, "CARTOLA"), (416, "DESDE"), (470, "HASTA"), (530, "PAGINA")):
            text(x, 169, s)
        text(76, 181, sample.account, size=9)
        text(366, 181, "77", size=9)
        text(408, 181, sample.period[0], size=9)
        text(459, 181, sample.period[1], size=9)
        text(532, 181, f"{n} DE {len(chunks)}", size=9)
        for x, s in ((73, "Saldo Inicial"), (253, "Cheques o Cargos"), (405, "Depósitos o Abonos"), (513, "Saldo Final")):
            text(x, 226, s)
        for x, v in zip((60, 253, 405, 509), summary):
            text(x, 241, _fmt(v), size=9)
        text(26, 256, "MOVIMIENTO DE SU CUENTA", size=9)
        text(425, 256, "SALDO DIARIO", size=9)
        for x, s in ((25, "FECHA"), (60, "NUMERO"), (118, "SUC"), (156, "DESCRIPCION"), (340, "CHEQUES"), (422, "DEPOSITOS"), (500, "SALDO")):
            text(x, 275, s, "hebo", 8)
        text(340, 284.6, "Y CARGOS", "hebo", 8)
        text(422, 284.6, "Y ABONOS", "hebo", 8)

        top = 298.0
        for row in chunk:
            if row[0] == "m":
                _, day, ref, branch, desc, amount = row
                if day:
                    text(26, top, day, "cour", 8)
                if ref:
                    text(62, top, ref, "cour", 8)
                text(118, top, branch, "cour", 8)
                text(160, top, desc, "cour", 8)
                right(419 if amount < 0 else 496, top, _fmt(abs(amount)))
            else:
                text(160, top, "--- Saldo Dia ---", "cour", 8)
                right(578, top, _fmt(row[1]))
            top += 9.0
        if n == len(chunks):
            text(160, top, "Resumen de Comisiones", "cour", 8)
            text(160, top + 9, "SIN COMISIONES EN EL PERIODO", "cour", 8)
        text(36, 724, "MENSAJES", "hebo", 8)
        text(36, 740, "Banco Santander Chile. 999.999 informese en la sucursal", size=7)
    return doc.tobytes()


# ---------------------------------------------------------------------------------------------
# Spreadsheet exports (.xlsx), written with the standard library: what a bank's "Descargar Excel" gives.
# ---------------------------------------------------------------------------------------------
Cell = str | int | float | None

# (day "DD/MM", branch, description, document, signed amount)
SheetMovement = tuple[str, str, str, str, int]

SANTANDER_XLSX_MOVEMENTS: tuple[SheetMovement, ...] = (
    ("01/09", "Sucursal Uno", "Compra Nacional VD SHOP ONE", "2432020", -900),
    ("02/09", "O.Gerencia", "0000000001 Transf de PERSONA UNO", "", 26_000),
    ("02/09", "Sucursal Uno", "Compra Nacional VD CAFE TWO", "2442020", -8_969),
    ("09/09", "Sucursal Uno", "0000000002 Transf. Plataforma Inversion", "6000000", 40_000),
    ("30/09", "Sucursal Uno", "*/Giro Nacional VD", "2732040", -10_000),
)


def santander_xlsx(
    movements: tuple[SheetMovement, ...] = SANTANDER_XLSX_MOVEMENTS,
    opening: int = 100_000,
    closing_override: int | None = None,
    daily_override: dict[str, int] | None = None,
) -> bytes:
    def money(v: int) -> str:
        return f"${_fmt(v)}"

    debits = -sum(m[4] for m in movements if m[4] < 0)
    credits = sum(m[4] for m in movements if m[4] > 0)
    closing = closing_override if closing_override is not None else opening - debits + credits
    rows: list[list[Cell]] = [
        ["Banco Santander", None, "", "", "Cartola de cuenta Corriente - Septiembre 2026"],
        ["Sr(a)", "PEREZ ANA", "", "", "Cartola N°", "12", ""],
        ["Rut", "11.111.111-1", "", "", "Desde", "31/08/2026", ""],
        ["E-mail", "ana.perez@example.com", "", "", "Hasta", "30/09/2026", ""],
        ["INFORMACIÓN CUENTA CORRIENTE"],
        ["Tipo de Cuenta:", "CTA CTE", "", "", "N° Cuenta:", "0-000-00-12345-6", ""],
        ["Saldo inicial:", money(opening), "", "", "Impuestos:", "$0", ""],
        ["Saldo final:", money(closing), "", "", "Depósitos:", "$0", ""],
        ["Otros abonos:", money(credits), "", "", "Cheques:", "$0", ""],
        ["Otros cargos:", money(debits), "", "", "Comisiones:", "", ""],
        ["DETALLE DE MOVIMIENTOS", None, None, None, None, "SALDOS DIARIOS"],
        ["FECHA", "SUCURSAL", "DESCRIPCIÓN", "N° DOCUMENTO", "CHEQUES Y OTROS CARGOS", "DEPOSITOS Y OTROS ABONOS", "SALDO"],
    ]
    balance = opening
    days = [m[0] for m in movements]
    for i, (day, branch, desc, doc, amount) in enumerate(movements):
        balance += amount
        last_of_day = i == len(days) - 1 or days[i + 1] != day
        saldo = (daily_override or {}).get(day, balance) if last_of_day else None
        rows.append([day, branch, desc, doc, -amount if amount < 0 else None, amount if amount > 0 else None, saldo])
    rows += [["", "", "Resumen de Comisiones"], ["", "", "SIN COMISIONES EN EL PERIODO"], ["MENSAJES"]]
    return xlsx(rows, "Cartola de Cuenta")


# (date "DD/MM/YYYY", bank category, detail, cuotas, bank-signed amount: positive = charge)
CardMovement = tuple[str, str, str, str, int | float]

BICE_NATIONAL: tuple[CardMovement, ...] = (
    ("11/10/2026", "Entretenimiento", "* SHOP ONE COMPRAS", "1 de 1", 7_500),
    ("05/10/2026", "Abonos", "MONTO CANCELADO", "", -120_990),
    ("05/10/2026", "Hogar", "STORE TWO COMPRAS", "1 de 1", 78_578),
    ("23/09/2026", "Hogar", "DL DELIVERY APP COMPRAS", "1 de 1", 7_700),
    ("23/09/2026", "Abonos", "DL DELIVERY APP REVCOMPRAS", "", -3_996),
)
BICE_INTERNATIONAL: tuple[CardMovement, ...] = (
    ("05/10/2026", "Abonos", "MONTO CANCELADO", "", -28.22),
    ("30/09/2026", "Entretenimiento", "APP STORE SUB COMPRAS INTVI", "", 8.22),
    ("29/09/2026", "Shopping", "SOFTWARE SUB COMPRAS INTVI", "", 20),
)


def bice_xlsx(movements: tuple[CardMovement, ...] = BICE_NATIONAL, international: bool = False, totals_override: tuple[str, str] | None = None) -> bytes:
    scope = "Internacionales" if international else "Nacionales"
    if totals_override:
        abonos, cargos = totals_override
    elif international:
        cents = [round(m[4] * 100) for m in movements]
        abonos = f"-{_usd(-sum(c for c in cents if c < 0))}\xa0US$"
        cargos = f"{_usd(sum(c for c in cents if c > 0))}\xa0US$"
    else:
        abonos = f"-{_fmt(-sum(m[4] for m in movements if m[4] < 0))}\xa0CLP"
        cargos = f"{_fmt(sum(m[4] for m in movements if m[4] > 0))}\xa0CLP"
    rows: list[list[Cell]] = [
        [],
        [None, None, None, None, f"Movimientos {scope} de Tarjeta de Crédito:"],
        [None, None, None, None, "Nº **** **** **** Ab3x"],
        [None, "Inicio periodo", None, None, "Total Abonos", "Total Cargos"],
        [None, "23/09/2026", None, None, abonos, cargos],
        [None, "Fecha", "Categoria", "Detalle", None, None, None, None, "Cuotas" if not international else "", "Monto US$" if international else "Monto $"],
    ]
    for day, category, detail, cuotas, amount in movements:
        rows.append([None, day, category, detail, None, None, None, None, cuotas, amount])
    rows.append([None, "* Movimientos sujetos a confirmación por los comercios respectivos."])
    rows.append([None, "Infórmate sobre la garantía estatal de los depósitos en tu banco o en www.cmfchile.cl"])
    return xlsx(rows, "Movimientos TC")


def _usd(cents: int) -> str:
    whole, frac = divmod(cents, 100)
    return f"{_fmt(whole)},{frac:02d}"


# ---------------------------------------------------------------------------------------------
# Credit card statement PDF (Chilean A–G format), fictional holder and merchants.
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class CardSample:
    """Totals are computed from the lines unless overridden, so a test can misprint one."""

    previous_billed: int = 100_000  # A
    payments: tuple[tuple[str, int], ...] = (("31/07/26", -100_000),)  # B
    one_cuota: tuple[tuple[str, str, int], ...] = (  # D
        ("31/07/26", "SHOP ONE SANTIAGO", 10_000),
        ("03/08/26", "CAFE TWO SANTIAGO", 5_300),
        ("21/08/26", "MARKET THREE SANTIAGO", 2_455),
    )
    # (date, merchant, purchase, n, of, cuota): E
    cuotas: tuple[tuple[str, str, int, int, int, int], ...] = (
        ("15/06/26", "MERCADOPAGO*STORE", 30_000, 2, 3, 10_000),
        ("14/08/26", "MERCADOPAGO*GADGET", 52_900, 1, 3, 17_633),
    )
    charges: tuple[tuple[str, str, int], ...] = (("10/08/26", "SHOP ONE COMPRA DIRECTA SANTIAGO", -4_850), ("27/08/26", "COMISION ADMINISTRACION MENSUAL", 4_904))  # G
    minimum: int = 5_000
    upcoming: tuple[int, int, int, int] | None = None  # printed; None = computed from the cuotas
    section_override: dict[str, int] = field(default_factory=dict)
    drop_line: str | None = None  # a merchant whose line is printed in a way the layout cannot read
    international: bool = True
    card_number: str = "XXXX XXX9 1111 4321"  # as the issuer prints it (masked); a test may print a full PAN


def card_pdf(sample: CardSample | None = None) -> bytes:
    import pymupdf

    s = sample or CardSample()
    sections = {
        "B": sum(a for _, a in s.payments),
        "C": 0,
        "D": sum(a for _, _, a in s.one_cuota),
        "E": sum(c[5] for c in s.cuotas),
        "F": 0,
        "G": sum(a for _, _, a in s.charges),
    }
    total = s.previous_billed + sum(sections.values())
    sections.update(s.section_override)
    upcoming = s.upcoming or (
        sum(c[5] if c[4] - c[3] > 1 else c[2] - c[5] * (c[4] - 1) for c in s.cuotas if c[4] > c[3]),
        sum(c[2] - c[5] * (c[4] - 1) for c in s.cuotas if c[4] - c[3] == 2),
        0,
        0,
    )

    def money(v: int) -> str:
        return f"$ {'-' if v < 0 else ''}{_fmt(abs(v))}"

    def line(place: str, day: str, code: str, desc: str, op: int, n: int, of: int, cuota: int) -> str:
        return f"{place} {day} {code} {desc} {money(op)} {money(op)} {n:02d}/{of:02d} {money(cuota)}".strip()

    national = [
        "1 de 2",
        "ESTADO DE CUENTA NACIONAL DE TARJETA DE CRÉDITO",
        "NOMBRE DEL TITULAR ANA PEREZ",
        f"N° DE TARJETA DE CRÉDITO {s.card_number}",
        "ANA.PEREZ@EXAMPLE.COM",
        "FECHA ESTADO DE CUENTA 27/08/2026",
        "I. INFORMACIÓN GENERAL",
        "CUPO TOTAL $ 500.000 $ 300.000 $ 200.000",
        "CUPO TOTAL AVANCE EN EFECTIVO $ 475.000 $ 0 $ 200.000",
        "PERÍODO FACTURADO 30/07/2026 27/08/2026",
        "inscritas en los Registros de Emisores de Tarjetas que lleva la CMF, en www.cmfchile.cl. PAGAR HASTA 15/09/2026",
        "II. DETALLE",
        "PERÍODO DE FACTURACIÓN ANTERIOR 26/06/2026 29/07/2026",
        f"MONTO FACTURADO A PAGAR (PERÍODO ANTERIOR) A {money(s.previous_billed)}",
        "2. PERÍODO ACTUAL",
        "1.TOTAL OPERACIONES",
        *(line("", d, "310700000000", "MONTO CANCELADO", a, 1, 1, a) for d, a in s.payments),
        f"TOTAL PAGOS A LA CUENTA B {money(sections['B'])}",
        "Sin Movimientos",
        f"TOTAL PAT A LA CUENTA C {money(sections['C'])}",
    ]
    page2 = [
        "2 de 2",
        "2. PERÍODO ACTUAL",
        *(
            (f"SANTIAGO {d} 0308{i:08d} {m} PRINTED {_fmt(a)}" if m == s.drop_line else line("SANTIAGO", d, f"0308{i:08d}", m, a, 1, 1, a))
            for i, (d, m, a) in enumerate(s.one_cuota)
        ),
        f"TOTAL TARJETA XXXX XXXX XXXX 4321 {money(sections['D'])}",
        f"TOTAL TRANSACCIONES EN UNA CUOTA D {money(sections['D'])}",
        *(line("LAS CONDES", d, f"2708{i:08d}", f"{m} TASA INT. 0,00%", p, n, of, c) for i, (d, m, p, n, of, c) in enumerate(s.cuotas)),
        f"TOTAL TRANSACCIONES EN CUOTAS E {money(sections['E'])}",
        f"TOTAL PRODUCTOS O SERVICIOS VOLUNTARIAMENTE CONTRATADOS F {money(sections['F'])}",
        "3.CARGOS, COMISIONES, IMPUESTOS Y ABONOS",
        *(line("", d, f"1108{i:08d}", m, a, 1, 1, a) for i, (d, m, a) in enumerate(s.charges)),
        f"TOTAL CARGOS, COMISIONES, IMPUESTOS Y ABONOS G {money(sections['G'])}",
        "III. INFORMACIÓN DE PAGO",
        f"MONTO TOTAL FACTURADO A PAGAR ( A+B+C+D+E+F+G ) {money(total)} EVOLUCIÓN MONTOS FACTURADOS Y PAGADOS",
        f"MONTO MÍNIMO A PAGAR {money(s.minimum)}",
        "ACTUAL SEPTIEMBRE OCTUBRE NOVIEMBRE DICIEMBRE 337.721 Monto Pagado",
        " ".join(money(v) for v in (sections["E"], *upcoming)) + " 168.861",
        "PRÓXIMO PERÍODO DE FACTURACIÓN 28/08/2026 24/09/2026",
    ]
    international = [
        "1 de 1",
        "ESTADO DE CUENTA INTERNACIONAL DE TARJETA DE CREDITO",
        f"N° DE TARJETA DE CREDITO {s.card_number}",
        "CUPO TOTAL US$ 1.000,00 US$ 18,99 US$ 981,01",
        "SALDO ANTERIOR FACTURADO US$ 22,41 PERIODO FACTURADO DESDE 30/07/2026",
        "ABONO REALIZADO US$ 22,41 PERIODO FACTURADO HASTA 27/08/2026",
        "TRASPASO DEUDA NACIONAL US$ 0,00 PAGAR HASTA 15/09/2026",
        "DEUDA TOTAL US$ 18,99",
        "TOTAL DE PAGOS US$ -22,41",
        "0308 31/07/26 Pago Dolar TEF CL -22,41 -22,41",
        "TOTAL DE COMPRAS US$ 18,99",
        "0408 24000000000000000000001 03/08/26 SOFTWARE ONE SOFTWARE.EXAMPLE US 10,00 10,00",
        "2408 74000000000000000000002 22/08/26 Music Stream Stockholm SE 8.250,00 8,99",
        "TOTAL TARJETA XXXX XXXX XXXX 4321 18,99",
        "COMISIONES, OTROS CARGOS Y ABONOS A LA CUENTA US$ 0,00",
    ]
    doc = pymupdf.open()
    for page_lines in (national, page2, *([international] if s.international else [])):
        page = doc.new_page(width=612, height=792)
        for k, text in enumerate(page_lines):
            page.insert_text((24, 30 + k * 11), text, fontname="helv", fontsize=6.5)
    return doc.tobytes()
