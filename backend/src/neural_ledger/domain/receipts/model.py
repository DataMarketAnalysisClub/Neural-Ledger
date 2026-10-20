"""Receipts (boletas) read from a photo or a PDF, and what the engine may conclude from them (ADR-039).

A receipt is evidence of one purchase. If it was paid by card, the next bank statement shows the same purchase,
so a receipt is never posted to the transaction ledger: it counts as logged spending only until a statement
charge matches it (same amount, a close date), and from then on the statement's line is the record.

Amounts come from a reader that can misread. A printed tax split (neto + IVA) or the SII stamp (timbre
electrónico, decoded from its PDF417 code) can confirm the total; a receipt whose total is missing, whose date
is missing or in the future, or whose sources disagree is stored unverified and never counted. The issuer's
name and the items are third-party text: DATA, never instructions.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import Enum

from ..agent.questions import ChoiceQuestion
from ..ledger.categorization import PostedTransaction
from ..ledger.entities import TransactionKind
from ..shared.hashing import content_id

# Reader rules, checks and matching; outputs carry it as params_version.
RECEIPTS_VERSION = "rc-0.1"
# A card purchase reaches the statement on the day or a few days later; a receipt can be photographed a day late.
MATCH_WINDOW_DAYS = 3


class DocumentKind(str, Enum):
    STATEMENT = "statement"
    RECEIPT = "receipt"
    INVESTMENT = "investment"  # a fund manager's statement or transactions certificate (ADR-044)
    UNKNOWN = "unknown"


# For decision models that answer closed questions (Jev, ADR-032). The text is the state and is untrusted: the
# answer is only a route, never an amount, and a low-confidence answer routes nowhere.
DOCUMENT_KIND_QUESTION = ChoiceQuestion(
    key="document_kind",
    prompt="Which kind of Chilean personal-finance document is this text read from?",
    options=tuple(k.value for k in DocumentKind),
    notes=(
        "A bank statement (cartola) or a credit card statement: many dated movements, balances, a period",
        "A receipt for one purchase (boleta, boleta electrónica, ticket, comprobante de venta): a store, items and one total",
        "An investment fund statement or transactions certificate (Fintual, an administradora general de fondos): fund shares, contributions, withdrawals",
        "Anything else: an invoice to a company, an ID, a letter, a photo without a financial document",
    ),
)

_RECEIPT_MARKS = re.compile(
    r"(boleta|ticket|comprobante de (?:venta|pago)|timbre electr[oó]nico|total a pagar|vuelto|cajer[oa]|"
    r"art[ií]culos?|cant\.?|precio unit|iva incluido|res\.? ?ex|importe|producto|propina|comensal|proforma|"
    r"pre-?cuenta|garz[oó]n|impuestos? inc)", re.I
)
# A TOTAL (as OCR may read it) followed by an amount: one purchase, when nothing says it is a statement.
_TOTAL_AMOUNT = re.compile(r"\btota\s?[l1I\]|](?![a-z]).{0,40}?\d", re.I | re.S)
# A fund manager's document: fund shares, contributions and withdrawals, never bank movements or a purchase. Banks
# print "cuotas" for installments too, so only words a fund manager prints count (ADR-044).
_INVESTMENT_MARKS = re.compile(
    r"(administradora general de fondos|investment statement|certificado de transacciones|net asset value|fund shares|"
    r"\brescates?\b|fondos? mutuos?)", re.I
)
_STATEMENT_MARKS = re.compile(
    r"(cartola|estado de cuenta|saldo inicial|saldo final|saldo anterior|saldo disponible|cupo (?:total|utilizado)|"
    r"cheques y cargos|dep[oó]sitos y abonos|per[ií]odo (?:facturado|de facturaci[oó]n)|monto (?:total )?facturado|"
    r"cuenta corriente|movimientos)", re.I
)


def kind_by_rules(text: str) -> DocumentKind | None:
    """The kind when the printed words leave no doubt, else None (a decision model may answer)."""
    receipt = len(_RECEIPT_MARKS.findall(text))
    statement = len(_STATEMENT_MARKS.findall(text))
    investment = len(_INVESTMENT_MARKS.findall(text))
    if investment >= 2 and investment > receipt + statement:  # first: a fund statement prints a "Total $..." line too
        return DocumentKind.INVESTMENT
    if receipt > 2 * statement:
        return DocumentKind.RECEIPT
    if statement > 2 * receipt:
        return DocumentKind.STATEMENT
    if statement == 0 and _TOTAL_AMOUNT.search(text):
        return DocumentKind.RECEIPT
    return None


@dataclass(frozen=True, slots=True)
class ReceiptStamp:
    """The SII stamp (timbre electrónico, TED) as decoded from the receipt's PDF417 code.

    Its RSA signature is not checked: the stamp confirms what the printed receipt says, it does not prove it.
    """

    issuer_rut: str
    document_type: int  # 39 boleta electrónica, 41 boleta exenta; facturas (33, 34) are not receipts
    folio: int
    issued_on: date
    total: int
    issuer_name: str | None = None  # third-party text
    first_item: str | None = None  # third-party text


@dataclass(frozen=True, slots=True)
class ReadReceipt:
    """A receipt as a reader read it. Every field can be wrong; `check` decides what may be trusted."""

    issuer: str  # third-party text: the store's name as printed
    issued_on: date | None
    total: int | None  # positive, minor units
    folio: str | None = None
    issuer_rut: str | None = None  # the store's RUT; used for the receipt's identity, never stored
    net: int | None = None  # neto, when printed
    tax: int | None = None  # IVA, when printed
    stamp: ReceiptStamp | None = None
    source: str = "text"  # text (a PDF's text layer) | ocr (a photo or a scan)
    confidence: float | None = None  # lowest reader confidence over the total's line (None = text layer)


class ReceiptIssueCode(str, Enum):
    TOTAL_MISSING = "TOTAL_MISSING"
    DATE_MISSING = "DATE_MISSING"
    DATE_IN_FUTURE = "DATE_IN_FUTURE"
    TAX_MISMATCH = "TAX_MISMATCH"  # neto + IVA does not give the total
    STAMP_MISMATCH = "STAMP_MISMATCH"  # the printed total or date disagrees with the SII stamp


@dataclass(frozen=True, slots=True)
class ReceiptIssue:
    code: ReceiptIssueCode
    message: str
    expected: int | None = None
    found: int | None = None


def total_of(read: ReadReceipt) -> int | None:
    """The printed total, or the stamp's when the print could not be read."""
    if read.total is not None:
        return read.total
    return read.stamp.total if read.stamp else None


def date_of(read: ReadReceipt) -> date | None:
    """The stamp's date when there is one (the reader parsed it from a fixed format), else the printed one."""
    if read.stamp is not None:
        return read.stamp.issued_on
    return read.issued_on


def check(read: ReadReceipt, today: date) -> tuple[ReceiptIssue, ...]:
    """Every reason not to trust this receipt's amount. None means it may be counted."""
    issues: list[ReceiptIssue] = []
    total = total_of(read)
    if total is None or total <= 0:
        issues.append(ReceiptIssue(ReceiptIssueCode.TOTAL_MISSING, "the total could not be read"))
    issued_on = date_of(read)
    if issued_on is None:
        issues.append(ReceiptIssue(ReceiptIssueCode.DATE_MISSING, "the date could not be read"))
    elif issued_on > today:
        issues.append(ReceiptIssue(ReceiptIssueCode.DATE_IN_FUTURE, f"the date {issued_on.isoformat()} is after today"))
    if read.net is not None and read.tax is not None and total is not None and read.net + read.tax != total:
        issues.append(ReceiptIssue(ReceiptIssueCode.TAX_MISMATCH, "neto plus IVA does not give the total", total, read.net + read.tax))
    stamp = read.stamp
    if stamp is not None:
        if read.total is not None and read.total != stamp.total:
            issues.append(ReceiptIssue(ReceiptIssueCode.STAMP_MISMATCH, "the printed total disagrees with the SII stamp", stamp.total, read.total))
        if read.issued_on is not None and read.issued_on != stamp.issued_on:
            issues.append(ReceiptIssue(ReceiptIssueCode.STAMP_MISMATCH, "the printed date disagrees with the SII stamp"))
    return tuple(issues)


def receipt_id(user_id: str, read: ReadReceipt) -> str:
    """The same receipt imported twice (a photo and its PDF, or the same photo again) gets the same id.

    The stamp's issuer and folio identify a boleta electrónica uniquely; without a stamp the store, folio, date
    and total are the best identity the print gives.
    """
    if read.stamp is not None:
        return content_id("rcpt", user_id, read.stamp.issuer_rut, read.stamp.document_type, read.stamp.folio)
    store = read.issuer_rut or read.issuer.casefold().strip()
    issued_on = date_of(read)
    return content_id("rcpt", user_id, store, read.folio, issued_on.isoformat() if issued_on else None, total_of(read))


@dataclass(frozen=True, slots=True)
class StoredReceipt:
    """What is kept of a receipt: personal data removed, the store's RUT left out (ADR-028)."""

    receipt_id: str
    user_id: str
    imported_at: datetime
    issuer: str  # redacted third-party text
    issued_on: date | None
    total: int | None
    currency: str
    folio: str | None
    stamped: bool  # the SII stamp was decoded
    source: str  # text | ocr
    confidence: float | None
    category: str  # gated like a statement line's: a CATEGORIES label or 'uncategorized'
    classifier: str
    category_confidence: float | None
    issues: tuple[ReceiptIssue, ...]
    corrected: bool = False  # the user corrected or confirmed its total or date (ADR-039): they, not a reader, vouch for it
    payment: str = "unknown"  # cash | card | unknown. Cash never reaches a statement, so it is never matched to a charge

    @property
    def verified(self) -> bool:
        return not self.issues


CASH, CARD, UNKNOWN_PAYMENT = "cash", "card", "unknown"
PAYMENTS = (CASH, CARD)
MANUAL = "manual"  # the source of an expense the user told the copilot about: no document, their word, their confirmation


MAX_RECEIPT_TOTAL = 100_000_000  # CLP; a larger "receipt" is a typo, not a purchase
EARLIEST_RECEIPT = date(2000, 1, 1)
# What a total typed by the user settles, and what a date typed by the user settles.
_SETTLED_BY_TOTAL = frozenset({ReceiptIssueCode.TOTAL_MISSING, ReceiptIssueCode.TAX_MISMATCH, ReceiptIssueCode.STAMP_MISMATCH})
_SETTLED_BY_DATE = frozenset({ReceiptIssueCode.DATE_MISSING, ReceiptIssueCode.DATE_IN_FUTURE, ReceiptIssueCode.STAMP_MISMATCH})


def correct(receipt: StoredReceipt, total: int | None, issued_on: date | None, today: date) -> StoredReceipt:
    """The receipt with the total and date the user typed: the issues those values settle are gone.

    Only the user corrects a receipt, in the app (never a model). Values outside sense are refused with ValueError: a
    total of zero or above MAX_RECEIPT_TOTAL, a date before 2000 or after today. The receipt keeps its identity.
    """
    if total is None and issued_on is None:
        raise ValueError("give the total, the date or both")
    if total is not None and not 0 < total <= MAX_RECEIPT_TOTAL:
        raise ValueError(f"the total must be between 1 and {MAX_RECEIPT_TOTAL:,} CLP")
    if issued_on is not None and not EARLIEST_RECEIPT <= issued_on <= today:
        raise ValueError("the date must be a past day, from 2000 on")
    settled = (_SETTLED_BY_TOTAL if total is not None else frozenset()) | (_SETTLED_BY_DATE if issued_on is not None else frozenset())
    return replace(
        receipt,
        total=receipt.total if total is None else total,
        issued_on=receipt.issued_on if issued_on is None else issued_on,
        issues=tuple(i for i in receipt.issues if i.code not in settled),
        corrected=True,
    )


def match_charges(
    receipts: Sequence[StoredReceipt], transactions: Sequence[PostedTransaction], window_days: int = MATCH_WINDOW_DAYS
) -> dict[str, str]:
    """receipt id -> the statement charge that records the same purchase.

    A charge matches a verified receipt with the same amount (a purchase of minus the total) dated from
    `window_days` before the receipt to `window_days` after it. Each charge records one receipt at most: receipts
    are matched in their order, each to the closest unused charge (the earlier one on a tie), so the answer
    does not depend on the store's order of transactions.
    """
    charges = sorted(
        (p for p in transactions if p.transaction.kind is TransactionKind.PURCHASE and p.transaction.amount < 0),
        key=lambda p: (p.transaction.date, p.transaction.txn_id),
    )
    used: set[str] = set()
    matched: dict[str, str] = {}
    for receipt in receipts:
        if not receipt.verified or receipt.total is None or receipt.issued_on is None or receipt.payment == CASH:
            continue
        candidates = [
            p for p in charges
            if p.transaction.txn_id not in used and p.user_id == receipt.user_id and -p.transaction.amount == receipt.total
            and abs((p.transaction.date - receipt.issued_on).days) <= window_days
        ]
        if candidates:
            best = min(candidates, key=lambda p: (abs((p.transaction.date - receipt.issued_on).days), p.transaction.date))
            used.add(best.transaction.txn_id)
            matched[receipt.receipt_id] = best.transaction.txn_id
    return matched
