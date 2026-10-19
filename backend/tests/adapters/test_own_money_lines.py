"""ADR-024, checking side: a layout marks the holder's own money moving (to savings, to the card) by rule.

Those lines are posted as `movement` by rule, never sent to a classifier, and left out of spending; the user
can still relabel them (ADR-023). The kind stays the amount's sign: the rule sets the label, not the money.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from neural_ledger.adapters.outbound.statements.banks.santander import SantanderCuentaMatica
from neural_ledger.adapters.outbound.statements.banks.santander_xlsx import SantanderCuentaCorrienteXlsx
from neural_ledger.adapters.outbound.statements.reader import StatementFileReader
from neural_ledger.adapters.outbound.statements.synthetic import SyntheticStatements
from neural_ledger.domain.ledger.categorization import MOVEMENT, RULE, classifiable, post_statement
from neural_ledger.domain.ledger.entities import TransactionKind
from neural_ledger.domain.statements.model import LineKind, StoredStatement, reconcile


@pytest.mark.parametrize("layout", [SantanderCuentaCorrienteXlsx(), SantanderCuentaMatica()])
@pytest.mark.parametrize(
    ("description", "own"),
    [
        ("0123456789 Transf a Ahorro", True),
        ("TRANSFERENCIA A CUENTA AHORRO", True),
        ("Transf a cuenta de ahorros", True),
        ("0123456789 Transf de Ahorro", True),  # money back from their savings: not income
        ("TRANSFERENCIA DESDE CUENTA AHORRO", True),
        ("COMPRA LIDER PAGO TARJETA", False),  # not at the start: a merchant's text, not the bank's own line
        ("Pago Tarjeta de Credito", True),
        ("PAGO TARJETA VISA", True),
        ("0123456789 TRANSFERENCIA A TERCEROS ARRIENDO", False),  # a third party: spending
        ("Compra Nacional VD LIDER", False),
        ("Transf a [PERSON]", False),
        ("Ahorro en cafe", False),
    ],
)
def test_santander_layouts_mark_own_money_lines(layout, description, own):
    assert (layout.line_kind(description) is LineKind.TRANSFER_OWN) is own


def _synthetic_statement():
    (sample,) = SyntheticStatements().checking(7, date(2026, 9, 1), months=1)
    (statement,) = StatementFileReader().read(sample.content)
    return statement


def test_a_synthetic_savings_transfer_is_read_as_own_money():
    statement = _synthetic_statement()
    own = [line for line in statement.lines if line.kind is LineKind.TRANSFER_OWN]
    assert [line.description.split(" ", 1)[1] for line in own] == ["Transf a Ahorro"]
    assert all(line.kind is None for line in statement.lines if line not in own)


def test_own_money_is_posted_as_movement_by_rule_and_never_classified():
    statement = _synthetic_statement()
    stored = StoredStatement("stmt_1", "camila", datetime(2026, 10, 1, tzinfo=UTC), statement, reconcile(statement).issues)
    assert stored.verified
    own = [line.index for line in statement.lines if line.kind is LineKind.TRANSFER_OWN]
    assert not {line.index for line in classifiable(stored)} & set(own)  # a classifier never sees it
    posted = {p.line_index: p for p in post_statement(stored, {}, "naive_bayes@test")}
    for index in own:
        p = posted[index]
        assert (p.transaction.category, p.classifier, p.confidence) == (MOVEMENT, RULE, None)
        assert p.transaction.kind is TransactionKind.PURCHASE  # money out, by sign: only the label is the rule's


def test_a_card_line_marked_as_own_money_is_a_card_payment():
    from neural_ledger.domain.ledger.categorization import transaction_kind
    from neural_ledger.domain.ledger.entities import AccountType
    from neural_ledger.domain.statements.model import StatementLine

    line = StatementLine(0, date(2026, 9, 5), "PAGO", 100_000, kind=LineKind.TRANSFER_OWN)
    assert transaction_kind(AccountType.CREDIT_CARD, line) is TransactionKind.CARD_PAYMENT
