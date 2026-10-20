"""Synthetic Fintual documents for tests. The repository is public: never commit a real statement.

`holdings_pdf` draws an "Investment Statement" and `movements_pdf` a "Certificado de transacciones" with a text layer
laid out like Fintual's, for a fictional holder. Both come from the same moves, so they verify and agree unless a test
changes something on purpose: every movement's pesos are its shares times the value per share, every day's shares
follow from the day before, and the statement's shares are the certificate's last ones.

The figures, by hand (pesos):
    contributions from the bank   100,000 + 50,000 + 100,000 + 30,000 + 22,500 + 22,500 + 15,333 + 45,000 = 385,333 (8)
    withdrawals to the bank       13,000 (1); a move of 33,000 between the "Casa" goal's funds is not money in or out
    net contributions             372,333, over 11 months (2025-11 to 2026-09), contributions in 6 of them
    monthly average               385,333 / 11 = 35,030.27 -> 35,030
    balances on 2026-10-14        Risky Norris A 62.7235 x 4,800 = 301,073; Conservative Clooney A 30 x 1,350.5 = 40,515;
                                  Moderate Pitt A 35 x 2,300.25 = 80,508.75 -> 80,509; total 422,097
    gain                          422,097 - 372,333 = 49,764, 13.4% of the net contributions
    per goal                      Viaje a Japón 285,073 (Risky Norris split by shares, largest remainder) less 245,000;
                                  Fondo de emergencia 16,000 + 40,515 = 56,515 less 52,333; Casa 80,509 less 75,000
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

HOLDER = "Valentina Rojas Fuentes"  # fictional
HOLDER_RUT = "12.345.678-5"  # fictional, passes the check digit
ISSUER_RUT = "76.543.210-3"  # fictional
STATEMENT_DAY = date(2026, 10, 14)
TRIP, RAINY_DAY, HOME = "Viaje a Japón", "Fondo de emergencia", "Casa"
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")


@dataclass(frozen=True)
class Move:
    day: date
    goal: str
    fund: str
    series: str
    shares: Decimal  # positive: a contribution; negative: a withdrawal
    share_value: Decimal
    internal: bool = False


MOVES: tuple[Move, ...] = (
    Move(date(2025, 11, 3), TRIP, "Risky Norris", "A", Decimal("25.0000"), Decimal("4000.0000")),
    Move(date(2025, 11, 3), RAINY_DAY, "Conservative Clooney", "A", Decimal("40.0000"), Decimal("1250.0000")),
    Move(date(2025, 12, 2), TRIP, "Risky Norris", "A", Decimal("24.3902"), Decimal("4100.0000")),
    Move(date(2026, 1, 15), HOME, "Very Conservative Streep", "A", Decimal("30.0000"), Decimal("1000.0000")),
    Move(date(2026, 3, 10), RAINY_DAY, "Conservative Clooney", "A", Decimal("-10.0000"), Decimal("1300.0000")),
    Move(date(2026, 5, 5), HOME, "Very Conservative Streep", "A", Decimal("-30.0000"), Decimal("1100.0000"), internal=True),
    Move(date(2026, 5, 5), HOME, "Moderate Pitt", "A", Decimal("15.0000"), Decimal("2200.0000"), internal=True),
    Move(date(2026, 6, 1), TRIP, "Risky Norris", "A", Decimal("5.0000"), Decimal("4500.0000")),
    Move(date(2026, 6, 1), TRIP, "Risky Norris", "A", Decimal("5.0000"), Decimal("4500.0000")),
    Move(date(2026, 7, 20), RAINY_DAY, "Risky Norris", "A", Decimal("3.3333"), Decimal("4600.0000")),
    Move(date(2026, 9, 15), HOME, "Moderate Pitt", "A", Decimal("20.0000"), Decimal("2250.0000")),
)
# Value per share on the statement's day; Streep and Brad are printed with no shares, as Fintual lists every fund.
NAV = {
    ("Risky Norris", "A"): Decimal("4800.0000"),
    ("Conservative Clooney", "A"): Decimal("1350.5000"),
    ("Moderate Pitt", "A"): Decimal("2300.2500"),
    ("Very Conservative Streep", "A"): Decimal("1150.0000"),
    ("Moderate Brad 107", "Z"): Decimal("0"),
}


def pesos(shares: Decimal, value: Decimal) -> int:
    return int((shares * value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def cl(value: Decimal, places: int = 4) -> str:
    """Chilean number: dot thousands, comma decimals ("4.800,0000")."""
    text = f"{value:,.{places}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def money(amount: int) -> str:
    return "$" + f"{amount:,}".replace(",", ".")


def movement_rows(moves: tuple[Move, ...] = MOVES) -> list[str]:
    """Certificate rows, newest first; rows of one day print that day's closing shares."""
    closing: dict[tuple[str, str, str, date], Decimal] = {}
    running: dict[tuple[str, str, str], Decimal] = defaultdict(Decimal)
    for m in sorted(moves, key=lambda m: m.day):
        key = (m.goal, m.fund, m.series)
        running[key] += m.shares
        closing[(*key, m.day)] = running[key]
    rows = []
    for m in sorted(moves, key=lambda m: m.day, reverse=True):
        after = closing[(m.goal, m.fund, m.series, m.day)]
        shares_in, shares_out = (m.shares, Decimal(0)) if m.shares > 0 else (Decimal(0), -m.shares)
        cells = [
            m.day.strftime("%d/%m/%Y"), m.goal, m.fund, m.series,
            cl(shares_in) if shares_in else "0", cl(shares_out) if shares_out else "0", cl(m.share_value), cl(after),
            money(pesos(shares_in, m.share_value)) if shares_in else "0", money(pesos(shares_out, m.share_value)) if shares_out else "0",
            "MLT interno" if m.internal else "Transferencia electronica", money(pesos(after, m.share_value)),
        ]
        rows.append(" ".join(cells))
    return rows


def holdings_rows(moves: tuple[Move, ...] = MOVES, nav: dict | None = None) -> tuple[list[str], int]:
    nav = NAV if nav is None else nav
    shares: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for m in moves:
        shares[(m.fund, m.series)] += m.shares
    rows, total = [], 0
    for (fund, series), value in nav.items():
        held = shares.get((fund, series), Decimal(0))
        balance = pesos(held, value)
        total += balance
        rows.append(f"FM Fintual {fund} {series} {cl(held)} ${cl(value)} {money(balance)}")
    return rows, total


def holdings_pdf(
    *, moves: tuple[Move, ...] = MOVES, nav: dict | None = None, day: date = STATEMENT_DAY, total_delta: int = 0, extra_line: str | None = None
) -> bytes:
    rows, total = holdings_rows(moves, nav)
    when = f"{MONTHS[day.month - 1]} {day.day}, {day.year}"  # English, whatever the machine's locale
    lines = [
        "INVESTMENT STATEMENT",
        f"As of today, {when}, Fintual Administradora General de Fondos S.A., RUT {ISSUER_RUT} declares that on",
        f"{when} {HOLDER}, RUT {HOLDER_RUT} maintained a balance of the following fund shares",
        "with the following detail, at the request of the holder:",
        "Fund Serie Shares Net Asset Value (CLP) Balance (CLP)",
        *rows,
        f"Total {money(total + total_delta)}",
        *([extra_line] if extra_line else []),
        "This statement does not certify future returns. Fund shares change value every day.",
        "Fintual Administradora General de Fondos",
    ]
    return _pdf(lines)


def movements_pdf(*, moves: tuple[Move, ...] = MOVES, rows: list[str] | None = None, extra_line: str | None = None) -> bytes:
    lines = [
        "CERTIFICADO DE TRANSACCIONES DE",
        "FONDOS MUTUOS",
        f"{STATEMENT_DAY.day} de octubre del {STATEMENT_DAY.year}",
        f"Fintual Administradora General de Fondos S.A. certifica que {HOLDER}, Rut {HOLDER_RUT}, registra los siguientes movimientos:",
        "Fecha Inversión Nombre Nombre Fondo Serie Aporte Cuotas Rescate Cuotas Valor Cuota Medio Saldo Cuotas Final Día",
        "Aporte Pesos Rescate Pesos Medio Saldo Pesos Final Día",
        *(movement_rows(moves) if rows is None else rows),
        *([extra_line] if extra_line else []),
        "Fintual Administradora General de Fondos",
    ]
    return _pdf(lines)


def _pdf(lines: list[str], per_page: int = 45) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    for start in range(0, len(lines), per_page):
        page = doc.new_page(width=842, height=595)  # landscape, like the certificate
        for i, line in enumerate(lines[start : start + per_page]):
            page.insert_text((30, 40 + 12 * i), line, fontsize=7)
    content = doc.tobytes()
    doc.close()
    return content
