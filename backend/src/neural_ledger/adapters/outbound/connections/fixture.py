"""Synthetic connections for offline runs, CI and the recorded demo (ADR-047): no network, no keys.

FixtureMcpClient answers as a made-up investment app ("Inversiones Demo"), whatever address the user gives, after the
same address check a live server gets, so the screens and the agent behave as they would live. Its tools cover each
case: two read-only tools, one that needs arguments and one that writes, which can never be enabled.

FixtureBankFeed is one synthetic checking account whose movements follow a fixed calendar from 2026-01-01: its balance
is always the opening balance plus every movement to date, so a second sync reconciles like a real one.
Every name and number here is invented.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from ....application.ports import Clock, ConnectorUnavailable, TargetRefused
from ....domain.connections.bank import BankAccount, BankMovement
from ....domain.connections.model import check_target

TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "get_portfolio",
        "description": "Saldo, aportes netos y ganancia de cada objetivo de inversión.",
        "annotations": {"readOnlyHint": True},
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_contributions",
        "description": "Aportes y rescates de los últimos seis meses.",
        "annotations": {"readOnlyHint": True},
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_fund",
        "description": "Detalle de un fondo.",
        "annotations": {"readOnlyHint": True},
        "inputSchema": {"type": "object", "properties": {"fund_id": {"type": "string"}}, "required": ["fund_id"]},
    },
    {
        "name": "invest",
        "description": "Invierte un monto en un objetivo.",
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
        "inputSchema": {"type": "object", "properties": {"amount": {"type": "integer"}}, "required": ["amount"]},
    },
)

ANSWERS: dict[str, Any] = {
    "get_portfolio": {
        "currency": "CLP",
        "goals": [
            {"name": "Fondo de emergencia", "balance": 1_850_000, "net_contributions": 1_800_000, "gain": 50_000, "currency": "CLP"},
            {"name": "Viaje", "balance": 640_000, "net_contributions": 600_000, "gain": 40_000, "currency": "CLP"},
        ],
    },
    "get_contributions": {
        "currency": "CLP",
        "months": [{"month": f"2026-{m:02d}", "contributed": 100_000, "withdrawn": 0, "currency": "CLP"} for m in range(5, 11)],
    },
}


class FixtureMcpClient:
    def list_tools(self, url: str, token: str | None) -> Sequence[Any]:
        _check(url)
        return [dict(t) for t in TOOLS]

    def call_tool(self, url: str, token: str | None, name: str) -> Any:
        _check(url)
        if name not in ANSWERS:
            raise ConnectorUnavailable("RPC_ERROR")
        return ANSWERS[name]


def _check(url: str) -> None:
    block = check_target(url, ("93.184.216.34",), allow_private=False)  # a documentation address: format checks only
    if block is not None:
        raise TargetRefused(block.value)


EPOCH = date(2026, 1, 1)
OPENING = 1_200_000
# (day of month, description, amount): a month of a synthetic checking account
CALENDAR: tuple[tuple[int, str, int], ...] = (
    (1, "REMUNERACION EMPRESA DEMO", 1_450_000),
    (3, "PAGO ARRIENDO", -520_000),
    (5, "COMPRA SUPERMERCADO DEMO", -86_000),
    (9, "PAGO CUENTA LUZ", -32_000),
    (12, "COMPRA FARMACIA DEMO", -18_500),
    (15, "TRANSF A AHORRO", -150_000),
    (18, "COMPRA SUPERMERCADO DEMO", -74_300),
    (22, "PAGO PLAN CELULAR", -19_990),
    (26, "COMPRA RESTAURANT DEMO", -27_800),
)


class FixtureBankFeed:
    name = "fintoc"
    public_key: str | None = None

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def start(self) -> str | None:
        return None

    def exchange(self, exchange_token: str) -> str:
        if not exchange_token:
            raise ConnectorUnavailable("PROTOCOL")
        return "link_fixture"

    def fetch(self, link_token: str, since: date | None) -> Sequence[tuple[BankAccount, Sequence[BankMovement]]]:
        if link_token != "link_fixture":
            raise ConnectorUnavailable("HTTP_401")
        today = self._clock.now().date()
        movements = _movements_until(today)
        balance = OPENING + sum(m.amount for m in movements)
        account = BankAccount("acc_fixture", "0-000-00-12345-6", "CLP", balance)
        return [(account, [m for m in movements if since is None or m.posted_on >= since])]


def _movements_until(today: date) -> list[BankMovement]:
    found: list[BankMovement] = []
    month = EPOCH
    while month <= today:
        for day, description, amount in CALENDAR:
            on = month.replace(day=day)
            if on <= today:
                found.append(BankMovement(f"mov_{on.isoformat()}_{day}", on, description, amount))
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return found
