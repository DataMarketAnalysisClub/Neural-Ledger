"""Financial models from an account's own imported statements (ADR-029 step 2).

`StatementModelSource` builds the ledger snapshot from the user's verified statements (domain) and runs the
stage-1 estimators on it, exactly as the sandbox-ledger source does with a fixture file. `FirstFoundModelSource`
puts it behind the persona fixtures: a persona keeps its fixture (the golden answers E01-E14 depend on it), and
any other user gets the model of their own statements, never anyone else's.

Like the sandbox-ledger source, estimation warnings stay inside the estimator (contracts/README.md).
"""

from __future__ import annotations

from collections.abc import Sequence

from ...domain.finance.estimation import estimate_model
from ...domain.finance.model import FinancialModel
from ...domain.finance.params import FinanceParams
from ...domain.ledger.snapshot import build_ledger_snapshot
from ...domain.shared.envelope import Status
from ...domain.shared.errors import InsufficientData, InvalidInput
from ..ports import FinancialModelSource, NotFound, StatementStore, TransactionStore


class StatementModelSource:
    def __init__(self, statements: StatementStore, transactions: TransactionStore, params: FinanceParams) -> None:
        self._statements = statements
        self._transactions = transactions
        self._params = params

    def load(self, user_id: str) -> FinancialModel:
        snapshot = build_ledger_snapshot(user_id, self._statements.for_user(user_id), self._transactions.for_user(user_id))
        envelope = estimate_model(snapshot, self._params)
        if envelope.status is Status.INVALID_INPUT:
            raise InvalidInput(envelope.field or "statements", envelope.message or "the statements could not be read as a ledger", envelope.allowed)
        if not envelope.ok or envelope.data is None:
            raise InsufficientData(envelope.missing or ("financial_model",), envelope.message or "the statements could not be estimated")
        return envelope.data


class FirstFoundModelSource:
    """The first source that knows the user: NotFound moves on to the next one; any other answer is final."""

    def __init__(self, sources: Sequence[FinancialModelSource]) -> None:
        if not sources:
            raise ValueError("at least one model source is needed")
        self._sources = tuple(sources)

    def load(self, user_id: str) -> FinancialModel:
        for source in self._sources[:-1]:
            try:
                return source.load(user_id)
            except NotFound:
                continue
        return self._sources[-1].load(user_id)
