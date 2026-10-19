"""ADR-024 and ADR-036, checking side: a layout marks the holder's own money moving by rule.

Money into or out of their savings or investment products is posted as `savings`, a payment to their card as
`movement`. Both are by rule, never sent to a classifier, and left out of spending; the user can still relabel
them (ADR-023). The kind stays the amount's sign: the rule sets the label, not the money.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from neural_ledger.adapters.outbound.statements.banks.santander import SantanderCuentaMatica
from neural_ledger.adapters.outbound.statements.banks.santander_xlsx import SantanderCuentaCorrienteXlsx
from neural_ledger.adapters.outbound.statements.reader import StatementFileReader
from neural_ledger.adapters.outbound.statements.synthetic import SyntheticStatements
from neural_ledger.domain.ledger.categorization import MOVEMENT, RULE, SAVINGS, classifiable, post_statement
from neural_ledger.domain.ledger.entities import TransactionKind
from neural_ledger.domain.statements.model import LineKind, StoredStatement, reconcile

SAVE, OWN = LineKind.SAVINGS, LineKind.TRANSFER_OWN


@pytest.mark.parametrize("layout", [SantanderCuentaCorrienteXlsx(), SantanderCuentaMatica()])
@pytest.mark.parametrize(
    ("description", "kind"),
    [
        ("0123456789 Transf a Ahorro", SAVE),
        ("TRANSFERENCIA A CUENTA AHORRO", SAVE),
        ("Transf a cuenta de ahorros", SAVE),
        ("0123456789 Transf de Ahorro", SAVE),  # money back from their savings: not income
        ("TRANSFERENCIA DESDE CUENTA AHORRO", SAVE),
        ("Fondo Mutuo Stgo.Sistematico P", SAVE),  # a scheduled mutual fund contribution
        ("Fondo Mutuo Sistemático P", SAVE),
        ("0000000300 FONDOS MUTUOS RESCATE", SAVE),  # money back from the fund
        ("Rescate Fondo Mutuo", SAVE),
        ("COMPRA LIDER PAGO TARJETA", None),  # not at the start: a merchant's text, not the bank's own line
        ("Compra Nacional FONDO MUTUO DE AHORRO SA", None),  # a purchase whose merchant text mentions a fund
        ("Pago Tarjeta de Credito", OWN),
        ("PAGO TARJETA VISA", OWN),
        ("0123456789 TRANSFERENCIA A TERCEROS ARRIENDO", None),  # a third party: spending
        ("Compra Nacional VD LIDER", None),
        ("Transf a [PERSON]", None),
        ("Ahorro en cafe", None),
        ("Fondo de Comercio LTDA", None),
    ],
)
def test_santander_layouts_mark_own_money_lines(layout, description, kind):
    assert layout.line_kind(description) is kind


def _synthetic_statement():
    (sample,) = SyntheticStatements().checking(7, date(2026, 9, 1), months=1)
    (statement,) = StatementFileReader().read(sample.content)
    return statement


def test_a_synthetic_savings_transfer_is_read_as_savings():
    statement = _synthetic_statement()
    own = [line for line in statement.lines if line.kind is LineKind.SAVINGS]
    assert [line.description.split(" ", 1)[1] for line in own] == ["Transf a Ahorro"]
    assert all(line.kind is None for line in statement.lines if line not in own)


def test_savings_are_posted_as_savings_by_rule_and_never_classified():
    statement = _synthetic_statement()
    stored = StoredStatement("stmt_1", "camila", datetime(2026, 10, 1, tzinfo=UTC), statement, reconcile(statement).issues)
    assert stored.verified
    own = [line.index for line in statement.lines if line.kind is LineKind.SAVINGS]
    assert own and not {line.index for line in classifiable(stored)} & set(own)  # a classifier never sees it
    posted = {p.line_index: p for p in post_statement(stored, {}, "naive_bayes@test")}
    for index in own:
        p = posted[index]
        assert (p.transaction.category, p.classifier, p.confidence) == (SAVINGS, RULE, None)
        assert p.transaction.kind is TransactionKind.PURCHASE  # money out, by sign: only the label is the rule's


def test_other_own_money_is_posted_as_movement_by_rule():
    from neural_ledger.domain.ledger.categorization import _rule_category
    from neural_ledger.domain.ledger.entities import AccountType
    from neural_ledger.domain.statements.model import StatementLine

    line = StatementLine(0, date(2026, 9, 5), "Pago Tarjeta de Credito", -100_000, kind=LineKind.TRANSFER_OWN)
    assert _rule_category(AccountType.CHECKING, line) == MOVEMENT


def test_a_card_line_marked_as_own_money_is_a_card_payment():
    from neural_ledger.domain.ledger.categorization import transaction_kind
    from neural_ledger.domain.ledger.entities import AccountType
    from neural_ledger.domain.statements.model import StatementLine

    for kind in (LineKind.TRANSFER_OWN, LineKind.SAVINGS):
        line = StatementLine(0, date(2026, 9, 5), "PAGO", 100_000, kind=kind)
        assert transaction_kind(AccountType.CREDIT_CARD, line) is TransactionKind.CARD_PAYMENT
