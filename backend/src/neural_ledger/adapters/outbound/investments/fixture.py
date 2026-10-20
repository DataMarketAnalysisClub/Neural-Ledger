"""Offline investment provider (ADR-044): a synthetic Fintual-like account, so linking, syncing and the agent's read
run with no network and no real account. CI, docker compose and the public demo use it.

Any email and password link. The token is derived from the email, so only a token this adapter issued reads the
goals; anything else is refused like an expired token. The goals are invented and say so: `synthetic` reaches the
snapshot, and the agent must mention it (INVESTMENTS_SYNTHETIC). Two amounts carry decimals on purpose, the way the
provider reports them, to exercise the single rounding to integer pesos.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal

from ....application.ports import InvestmentAccessRejected
from ....domain.investments.model import ReportedGoal

FIXTURE_GOALS: tuple[ReportedGoal, ...] = (
    ReportedGoal("101", "Viaje", Decimal("1264350.4"), Decimal("1200000")),
    ReportedGoal("102", "Fondo de emergencia", Decimal("815220"), Decimal("800000")),
    ReportedGoal("103", "Largo plazo", Decimal("2431899.6"), Decimal("2100000")),
)


class FixtureInvestmentProvider:
    name = "fixture"
    provider = "fintual"
    synthetic = True

    def authenticate(self, email: str, password: str) -> str:
        return _token(email)

    def goals(self, email: str, token: str) -> tuple[ReportedGoal, ...]:
        if token != _token(email):
            raise InvestmentAccessRejected("this token was not issued by the offline provider")
        return FIXTURE_GOALS


def _token(email: str) -> str:
    return "fixture-" + hashlib.sha256(email.encode("utf-8")).hexdigest()[:24]
