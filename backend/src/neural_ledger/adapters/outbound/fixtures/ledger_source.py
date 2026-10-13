"""FinancialModelSource adapter backed by the sandbox ledger (data/ledgers/<user>.json).

It parses the ledger into a LedgerSnapshot and runs Role A's estimators (stage 1). Use cases
cannot tell it apart from PersonaFixtureSource: both return a FinancialModel. The persona
fixtures stay as the golden reference the estimators must reproduce.

Parsing is strict and never raises anything but InvalidInput, naming the offending field
(e.g. `transactions[12].kind`): no silent truncation of 12.7 to 12, no "12" accepted as a
number. Value rules (limits, currencies, dates after as_of) live in the estimator; the
contract is contracts/ledger/ledger.schema.json.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

from ....application.ports import ModelEvidence, NotFound
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
from ....domain.shared.envelope import Status
from ....domain.shared.errors import InsufficientData, InvalidInput
from ....domain.shared.month import Month

E = TypeVar("E", bound=Enum)


def _get(obj: Any, key: str, path: str) -> Any:
    if not isinstance(obj, dict):
        raise InvalidInput(path, f"{path} must be an object")
    if key not in obj:
        raise InvalidInput(f"{path}.{key}" if path else key, "required field is missing")
    return obj[key]


def _int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidInput(field, "must be an integer amount in minor units")
    return value


def _str(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise InvalidInput(field, "must be a string")
    return value


def _enum(enum: type[E], value: Any, field: str) -> E:
    try:
        return enum(value)
    except (ValueError, TypeError):
        raise InvalidInput(field, f"unknown value {str(value)[:40]!r}", tuple(e.value for e in enum)) from None


def _date(value: Any, field: str) -> date:
    try:
        return date.fromisoformat(_str(value, field))
    except ValueError:
        raise InvalidInput(field, "must be a date YYYY-MM-DD") from None


def _month(value: Any, field: str) -> Month:
    try:
        return Month.parse(_str(value, field))
    except ValueError:
        raise InvalidInput(field, "must be a month YYYY-MM") from None


def _list(obj: dict, key: str, item: Callable[[Any, str], Any], *, required: bool = True) -> tuple:
    if key not in obj and not required:
        return ()
    values = _get(obj, key, "")
    if not isinstance(values, list):
        raise InvalidInput(key, "must be a list")
    return tuple(item(v, f"{key}[{i}]") for i, v in enumerate(values))


def _account(a: Any, path: str) -> Account:
    return Account(
        _str(_get(a, "account_id", path), f"{path}.account_id"),
        _enum(AccountType, _get(a, "type", path), f"{path}.type"),
        _int(_get(a, "balance", path), f"{path}.balance"),
        _str(_get(a, "currency", path), f"{path}.currency"),
    )


def _installment(info: Any, path: str) -> InstallmentInfo | None:
    if info is None:
        return None
    rate = info.get("monthly_rate") if isinstance(info, dict) else None
    try:
        parsed_rate = Decimal(_str(rate, f"{path}.monthly_rate")) if rate is not None else None
    except InvalidOperation:
        raise InvalidInput(f"{path}.monthly_rate", "must be a decimal number as text") from None
    return InstallmentInfo(
        plan_id=_str(_get(info, "plan_id", path), f"{path}.plan_id"),
        installment_number=_int(_get(info, "installment_number", path), f"{path}.installment_number"),
        installment_total=_int(_get(info, "installment_total", path), f"{path}.installment_total"),
        original_amount=_int(_get(info, "original_amount", path), f"{path}.original_amount"),
        monthly_rate=parsed_rate,
    )


def _transaction(t: Any, path: str) -> Transaction:
    return Transaction(
        txn_id=_str(_get(t, "txn_id", path), f"{path}.txn_id"),
        account_id=_str(_get(t, "account_id", path), f"{path}.account_id"),
        date=_date(_get(t, "date", path), f"{path}.date"),
        amount=_int(_get(t, "amount", path), f"{path}.amount"),
        merchant_raw=_str(t.get("merchant_raw", ""), f"{path}.merchant_raw"),
        category=_str(t.get("category", ""), f"{path}.category"),
        kind=_enum(TransactionKind, _get(t, "kind", path), f"{path}.kind"),
        installment=_installment(t.get("installment"), f"{path}.installment"),
    )


def _goal(g: Any, path: str) -> Goal:
    return Goal(
        _str(_get(g, "goal_id", path), f"{path}.goal_id"),
        _str(_get(g, "name", path), f"{path}.name"),
        _int(_get(g, "target_amount", path), f"{path}.target_amount"),
        _month(_get(g, "deadline", path), f"{path}.deadline"),
        _int(_get(g, "saved_amount", path), f"{path}.saved_amount"),
    )


def _bucket(b: Any, path: str) -> SavingsBucket:
    return SavingsBucket(_str(_get(b, "bucket", path), f"{path}.bucket"), _int(_get(b, "amount", path), f"{path}.amount"))


def parse_ledger(raw: Any) -> LedgerSnapshot:
    if not isinstance(raw, dict):
        raise InvalidInput("ledger", "the ledger must be a JSON object")
    profile = _get(raw, "income_profile", "")
    contracted = profile.get("contracted_net") if isinstance(profile, dict) else None
    return LedgerSnapshot(
        user_id=_str(_get(raw, "user_id", ""), "user_id"),
        currency=_str(_get(raw, "currency", ""), "currency"),
        as_of=_date(_get(raw, "as_of", ""), "as_of"),
        ledger_version=str(raw.get("ledger_version", "")),
        accounts=_list(raw, "accounts", _account),
        transactions=_list(raw, "transactions", _transaction),
        goals=_list(raw, "goals", _goal, required=False),
        buckets=_list(raw, "buckets", _bucket, required=False),
        income_profile=IncomeProfile(
            type=_enum(IncomeType, _get(profile, "type", "income_profile"), "income_profile.type"),
            contracted_net=_int(contracted, "income_profile.contracted_net") if contracted is not None else None,
            payday_rule=_str(profile.get("payday_rule", "last_business_day"), "income_profile.payday_rule"),
        ),
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
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise InvalidInput("ledger", "the ledger file is not valid JSON") from None
        return parse_ledger(raw)

    def load(self, user_id: str) -> FinancialModel:
        return self.load_with_evidence(user_id)[0]

    def load_with_evidence(self, user_id: str) -> tuple[FinancialModel, ModelEvidence]:
        """Estimate once; the model plus the estimator's snapshot id, facts and warnings."""
        envelope = estimate_model(self.snapshot(user_id), self._params)
        if envelope.status is Status.INVALID_INPUT:
            raise InvalidInput(envelope.field or "ledger", envelope.message or "invalid ledger", envelope.allowed)
        if not envelope.ok or envelope.data is None or envelope.snapshot_id is None:
            raise InsufficientData(envelope.missing or ("financial_model",), envelope.message or "the ledger could not be estimated")
        return envelope.data, ModelEvidence(envelope.snapshot_id, envelope.facts, envelope.warnings)
