"""Synthetic cartolas for tests. The repository is public: never commit a real statement.

`santander_pdf` draws a fictional 'Estado CuentaMática' with the real layout's coordinates,
fonts and two-line header, so the whole read path (pdfplumber → rebuild → Bank) is exercised.
Totals and daily balances are computed from the movements unless a test overrides them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
