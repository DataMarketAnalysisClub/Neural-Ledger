"""FinancialModelSource adapter that reads calibrated persona fixtures (data/personas/<user>.json).

The other implementation, a ledger-backed source, will run Role A's estimators over the
sandbox ledger. Use cases cannot tell the difference: both return a FinancialModel.
"""

from __future__ import annotations

import json
from datetime import date
from fractions import Fraction
from pathlib import Path
from typing import Any

from ....application.ports import NotFound
from ....domain.finance.model import (
    Balances,
    CategorySpend,
    Commitment,
    CommitmentType,
    FinancialModel,
    IncomeModel,
    SpendModel,
)
from ....domain.finance.profile import RiskProfile
from ....domain.ledger.entities import Goal, IncomeType
from ....domain.shared.hashing import sha256_hex
from ....domain.shared.month import Month
from ....domain.user.profile import UserProfile


class PersonaFixtureSource:
    def __init__(self, personas_dir: Path) -> None:
        self._dir = Path(personas_dir)

    def _read(self, user_id: str) -> tuple[dict[str, Any], str]:
        if not user_id.isidentifier():
            raise NotFound(f"unknown user {user_id!r}")
        path = self._dir / f"{user_id}.json"
        if not path.is_file():
            raise NotFound(f"no persona fixture for {user_id!r}")
        text = path.read_text(encoding="utf-8")
        return json.loads(text), sha256_hex(text)[:12]

    def user_ids(self) -> tuple[str, ...]:
        return tuple(sorted(p.stem for p in self._dir.glob("*.json")))

    def load(self, user_id: str) -> FinancialModel:
        raw, digest = self._read(user_id)
        return parse_model(raw, source_version=f"fixture:{user_id}:{digest}")

    def profile(self, user_id: str) -> UserProfile:
        raw, _ = self._read(user_id)
        profile = raw.get("profile", {})
        tolerance = profile.get("declared_tolerance")
        return UserProfile(
            user_id=raw["user_id"],
            display_name=raw.get("display_name", raw["user_id"]),
            language=profile.get("language", "en"),
            declared_tolerance=RiskProfile.parse(tolerance) if tolerance else None,
        )


def parse_model(raw: dict[str, Any], *, source_version: str) -> FinancialModel:
    balances = raw["balances"]
    income = raw["income"]
    spend = raw["spend"]
    return FinancialModel(
        user_id=raw["user_id"],
        currency=raw["currency"],
        as_of=date.fromisoformat(raw["as_of"]),
        first_cycle=Month.parse(raw["first_cycle"]),
        balances=Balances(
            checking=int(balances["checking"]),
            reserve=int(balances["reserve"]),
            goal_buckets={k: int(v) for k, v in balances.get("goal_buckets", {}).items()},
        ),
        income=IncomeModel(
            type=IncomeType(income["type"]),
            typical=int(income["typical"]),
            conservative=int(income["conservative"]),
            cv=Fraction(str(income["cv"])),
            method=income["method"],
        ),
        commitments=tuple(
            Commitment(
                commitment_id=c["commitment_id"],
                type=CommitmentType(c["type"]),
                label=c["label"],
                amount=int(c["amount"]),
                first_due=Month.parse(c["first_due"]),
                last_due=Month.parse(c["last_due"]) if c.get("last_due") else None,
                confidence=float(c.get("confidence", 1.0)),
                installments_total=c.get("installments_total"),
                evidence_txn_ids=tuple(c.get("evidence_txn_ids", ())),
            )
            for c in raw.get("commitments", ())
        ),
        spend=SpendModel(
            categories=tuple(
                CategorySpend(s["category"], int(s["p50"]), int(s["p80"]), bool(s["essential"]))
                for s in spend["categories"]
            ),
            seasonal_factors={int(k): Fraction(str(v)) for k, v in spend.get("seasonal_factors", {}).items()},
            window_months=int(spend.get("window_months", 12)),
        ),
        goals=tuple(
            Goal(g["goal_id"], g["name"], int(g["target_amount"]), Month.parse(g["deadline"]), int(g["saved_amount"]))
            for g in raw.get("goals", ())
        ),
        source_version=source_version,
        largest_one_off_expense=int(raw.get("largest_one_off_expense", 0)),
    )
