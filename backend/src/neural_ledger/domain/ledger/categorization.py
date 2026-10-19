"""Post a verified bank statement into the ledger: one Transaction per statement line.

Everything here is deterministic. The only model input is a CategoryGuess per classifiable line,
and it is gated: a label outside CATEGORIES or below the confidence floor becomes 'uncategorized'.
A category is a label for spend breakdowns, never an amount, a kind or a permission; amounts
and kinds come from the reconciled statement alone:

    checking account   deposit → income (rule)          charge → purchase (classified)
    credit card        payment → card_payment, 'movement' (rule: the holder's own money, ADR-024)
                       refund, fee → refund, fee (classified)   anything else → purchase (classified)
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace

from ..agent.questions import ChoiceQuestion
from ..shared.hashing import content_id
from ..statements.model import LineKind, StatementLine, StoredStatement
from .entities import AccountType, InstallmentInfo, Transaction, TransactionKind

CATEGORIZATION_VERSION = "cat-0.5"  # posting rules (own money by rule) + vocabulary + category question + user categories; outputs carry it as params_version

# Spending categories a classifier may choose. The first six are the personas' categories.
CATEGORY_OPTIONS = ("groceries", "dining", "health", "shopping", "transport", "utilities", "entertainment", "other")
CATEGORIES = frozenset(CATEGORY_OPTIONS)

# The same vocabulary as a closed question, for models that answer one (Jev, ADR-032). The line's text is the
# state and is untrusted: whatever it says, the answer is only a guess that `accept` gates below.
CATEGORY_QUESTION = ChoiceQuestion(
    key="category",
    prompt="Which spending category best matches this line of a Chilean bank or credit card statement?",
    options=CATEGORY_OPTIONS,
    notes=(
        "Supermarkets and food stores: Lider, Jumbo, Unimarc, Santa Isabel, Tottus, aCuenta, minimarkets",
        "Restaurants, cafés, fast food and food delivery: Starbucks, McDonald's, Uber Eats, PedidosYa, Rappi",
        "Pharmacies, clinics, doctors, labs, dentists and health insurance: Cruz Verde, Salcobrand, Ahumada",
        "Retail and online shopping, clothes, electronics, home improvement: Falabella, Paris, Mercado Libre, Sodimac",
        "Rides, fuel, public transport, tolls and parking: Uber, Cabify, Copec, Shell, Metro, Biotren, TAG",
        "Household services and bills: electricity, water, gas, internet, mobile and phone plans (CGE, Essbio, Entel, WOM, VTR)",
        "Streaming, music, games, cinema and events: Netflix, Spotify, HBO Max, Steam, Cinemark",
        "Spending that fits none of the categories above, such as a transfer to another person",
    ),
)
INCOME = "income"
MOVEMENT = "movement"  # "Movimiento": money between the holder's own accounts, e.g. paying the card (ADR-024)
UNCATEGORIZED = "uncategorized"
# Naive Bayes over 8 classes gives ~0.2 to merchants it has never seen and 0.7+ to ones it has.
MIN_CATEGORY_CONFIDENCE = 0.5
RULE = "rule"  # classifier name recorded when a rule, not a model, chose the category
USER = "user"  # classifier name recorded when the user chose the category (ADR-023); it wins over any model


@dataclass(frozen=True, slots=True)
class CategoryGuess:
    """A classifier's answer for one description. Untrusted until post_statement gates it."""

    category: str
    confidence: float
    source: str | None = None  # the model that answered, when a chain may mix them; None = the posting classifier

    def __post_init__(self) -> None:
        if not (math.isfinite(self.confidence) and 0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence!r}")


@dataclass(frozen=True, slots=True)
class PostedTransaction:
    """A ledger transaction with where it came from and how its category was chosen."""

    user_id: str
    currency: str
    transaction: Transaction
    statement_id: str
    line_index: int
    classifier: str  # the method that chose the category ("rule" for income)
    confidence: float | None  # the model's confidence, also when it was too low to accept

    @property
    def categorized(self) -> bool:
        return self.transaction.category != UNCATEGORIZED


# What the user may set, by kind (ADR-023, ADR-024). The kind and the amount come from the statement and never
# change: a deposit can be income or the holder's own money, a card payment is always the holder's own money
# (counting it as spending would count the cuotas twice), and any charge can take a spending category or Movimiento.
_USER_CATEGORIES = {
    TransactionKind.INCOME: frozenset({INCOME, MOVEMENT}),
    TransactionKind.CARD_PAYMENT: frozenset({MOVEMENT}),
}
_USER_SPENDING_CATEGORIES = CATEGORIES | {MOVEMENT}


def user_categories(kind: TransactionKind) -> frozenset[str]:
    return _USER_CATEGORIES.get(kind, _USER_SPENDING_CATEGORIES)


def relabel(posted: PostedTransaction, category: str) -> PostedTransaction | None:
    """The transaction with the user's category, or None if its kind cannot take that category.

    Only the label changes, with classifier "user" and no confidence; the amount, the kind and the source line stay.
    """
    if category not in user_categories(posted.transaction.kind):
        return None
    return replace(posted, transaction=replace(posted.transaction, category=category), classifier=USER, confidence=None)


def accept(guess: CategoryGuess | None, min_confidence: float = MIN_CATEGORY_CONFIDENCE) -> str:
    if guess is None or guess.category not in CATEGORIES or guess.confidence < min_confidence:
        return UNCATEGORIZED
    return guess.category


_CARD_KINDS = {
    LineKind.PAYMENT: TransactionKind.CARD_PAYMENT,
    LineKind.REFUND: TransactionKind.REFUND,
    LineKind.FEE: TransactionKind.FEE,
    LineKind.PURCHASE: TransactionKind.PURCHASE,
    LineKind.TRANSFER_OWN: TransactionKind.CARD_PAYMENT,  # on a card, the holder's own money moving is a payment to it
}


def transaction_kind(account_type: AccountType, line: StatementLine) -> TransactionKind:
    """From the statement alone: the layout's line kind on a card, the sign on any other account."""
    if account_type is AccountType.CREDIT_CARD:
        if line.kind is not None:
            return _CARD_KINDS[line.kind]
        return TransactionKind.REFUND if line.amount > 0 else TransactionKind.PURCHASE
    return TransactionKind.INCOME if line.amount > 0 else TransactionKind.PURCHASE


_RULE_CATEGORIES = {TransactionKind.INCOME: INCOME, TransactionKind.CARD_PAYMENT: MOVEMENT}


def _rule_category(account_type: AccountType, line: StatementLine) -> str | None:
    """The category a rule gives this line, or None if a classifier chooses it.

    The layout's own-money mark (ADR-024) wins over the sign: money to the holder's savings or card is a Movimiento,
    never spending, and money back from their own account is not income.
    """
    if line.kind is LineKind.TRANSFER_OWN:
        return MOVEMENT
    return _RULE_CATEGORIES.get(transaction_kind(account_type, line))


def classifiable(stored: StoredStatement) -> tuple[StatementLine, ...]:
    """The lines whose category a classifier chooses; the others get theirs by rule."""
    s = stored.statement
    return tuple(line for line in s.lines if _rule_category(s.account_type, line) is None)


def post_statement(
    stored: StoredStatement,
    guesses: Mapping[int, CategoryGuess],
    classifier: str,
    *,
    min_confidence: float = MIN_CATEGORY_CONFIDENCE,
) -> tuple[PostedTransaction, ...]:
    """Classifiable lines are categorized by `guesses` (keyed by line index); the rest by rule.

    Each transaction records the model that chose its category: the guess's `source` when it has one
    (a fallback chain answers some lines with one model and some with another), else `classifier`.
    Only a final statement that reconciles is posted: an unverified amount must not reach the
    ledger the financial core computes from, and a provisional export would be posted twice.
    """
    if not stored.verified:
        raise ValueError("only a verified statement can be posted to the ledger")
    s = stored.statement
    if s.provisional:
        raise ValueError("a provisional statement (unbilled movements) is never posted")
    account_id = f"{s.bank}:{s.account_ref}"
    posted = []
    for line in s.lines:
        kind = transaction_kind(s.account_type, line)
        rule = _rule_category(s.account_type, line)
        if rule is not None:
            category, method, confidence = rule, RULE, None
        else:
            guess = guesses.get(line.index)
            category = accept(guess, min_confidence)
            method = (guess.source if guess else None) or classifier
            confidence = guess.confidence if guess else None
        txn = Transaction(
            txn_id=content_id("txn", stored.user_id, stored.statement_id, line.index),
            account_id=account_id,
            date=line.posted_on,
            amount=line.amount,
            merchant_raw=line.description,
            category=category,
            kind=kind,
            installment=_installment(line),
        )
        posted.append(PostedTransaction(stored.user_id, s.currency, txn, stored.statement_id, line.index, method, confidence))
    return tuple(posted)


def _installment(line: StatementLine) -> InstallmentInfo | None:
    inst = line.installment
    if inst is None or inst.total < 2 or inst.original_amount is None:
        return None
    # One plan across statements: same purchase date, amount, cuotas and merchant text.
    plan_id = content_id("plan", inst.purchased_on, inst.original_amount, inst.total, line.description)
    return InstallmentInfo(plan_id, inst.number, inst.total, inst.original_amount, inst.monthly_rate)
