"""FinancialModelSource adapter backed by the sandbox ledger (data/ledgers/<user>.json).

It parses the ledger into a LedgerSnapshot and runs Role A's estimators (stage 1). Use cases
cannot tell it apart from PersonaFixtureSource: both return a FinancialModel. The persona
fixtures stay as the golden reference the estimators must reproduce.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from ....application.ports import NotFound
from ....domain.finance.estimation import estimate_model
from ....domain.finance.model import FinancialModel
from ....domain.finance.params import FinanceParams
from ....domain.ledger.entities import (
    Account,
    AccountType,
    Goal,
    IncomeProfile,
    IncomeType,
    InstallmentInfo,
    LedgerSnapshot,
    SavingsBucket,
    Transaction,
    TransactionKind,
)
from ....domain.shared.errors import InsufficientData
from ....domain.shared.month import Month


def parse_ledger(raw: dict[str, Any]) -> LedgerSnapshot:
    profile = raw["income_profile"]
    return LedgerSnapshot(
        user_id=raw["user_id"],
        currency=raw["currency"],
        as_of=date.fromisoformat(raw["as_of"]),
        ledger_version=str(raw["ledger_version"]),
        accounts=tuple(
            Account(a["account_id"], AccountType(a["type"]), int(a["balance"]), a["currency"]) for a in raw["accounts"]
        ),
        transactions=tuple(_transaction(t) for t in raw["transactions"]),
        goals=tuple(
            Goal(g["goal_id"], g["name"], int(g["target_amount"]), Month.parse(g["deadline"]), int(g["saved_amount"]))
            for g in raw.get("goals", ())
        ),
        buckets=tuple(SavingsBucket(b["bucket"], int(b["amount"])) for b in raw.get("buckets", ())),
        income_profile=IncomeProfile(
            type=IncomeType(profile["type"]),
            contracted_net=int(profile["contracted_net"]) if profile.get("contracted_net") is not None else None,
            payday_rule=profile.get("payday_rule", "last_business_day"),
        ),
    )


def _transaction(t: dict[str, Any]) -> Transaction:
    info = t.get("installment")
    return Transaction(
        txn_id=str(t["txn_id"]),
        account_id=str(t["account_id"]),
        date=date.fromisoformat(t["date"]),
        amount=int(t["amount"]),
        merchant_raw=str(t.get("merchant_raw", "")),
        category=str(t.get("category", "")),
        kind=TransactionKind(t["kind"]),
        installment=InstallmentInfo(
            plan_id=str(info["plan_id"]),
            installment_number=int(info["installment_number"]),
            installment_total=int(info["installment_total"]),
            original_amount=int(info["original_amount"]),
            monthly_rate=Decimal(str(info["monthly_rate"])) if info.get("monthly_rate") is not None else None,
        )
        if info
        else None,
    )


class LedgerModelSource:
    def __init__(self, ledgers_dir: Path, params: FinanceParams) -> None:
        self._dir = Path(ledgers_dir)
        self._params = params

    def snapshot(self, user_id: str) -> LedgerSnapshot:
        if not user_id.isidentifier():
            raise NotFound(f"unknown user {user_id!r}")
        path = self._dir / f"{user_id}.json"
        if not path.is_file():
            raise NotFound(f"no ledger for {user_id!r}")
        return parse_ledger(json.loads(path.read_text(encoding="utf-8")))

    def load(self, user_id: str) -> FinancialModel:
        envelope = estimate_model(self.snapshot(user_id), self._params)
        if not envelope.ok or envelope.data is None:
            missing = envelope.missing or ((envelope.field,) if envelope.field else ("financial_model",))
            raise InsufficientData(missing, envelope.message or "the ledger could not be estimated")
        return envelope.data
