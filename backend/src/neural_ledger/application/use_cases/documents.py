"""Drop any document on the copilot: route it, read it, record it, and say what it changes (ADR-039).

    file ─► peek (format + first page's text)
         ─► route: a spreadsheet is a statement; else the printed words (domain rules); else the decision chain
            (Jev first when configured) on the REDACTED text, accepted only above MIN_ROUTE_CONFIDENCE
         ├─ statement ─► StatementUseCases.import_statement (unchanged: redact, reconcile, post, audit)
         └─ receipt ───► read (print + SII stamp) ─► check (domain) ─► redact the store's name ─► categorize
                         (classifier port, gated by the domain) ─► store once ─► match to a statement charge
         ─► spending check-in: what is left of the cycle's conservative assumption, per day (FinancialUseCases)

Every step is returned as a workflow step for the UI and audited. Models only route a document and guess a
category; amounts come from the document, and every figure the copilot later says comes from the engine.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date

from ...domain.agent.amounts import written_amounts
from ...domain.agent.untrusted import sanitize, wrap_untrusted
from ...domain.audit.events import Actor, AuditDraft, AuditKind
from ...domain.finance.spending import LoggedSpend, SpendingCheck
from ...domain.ledger.categorization import CATEGORIES, UNCATEGORIZED, PostedTransaction, accept
from ...domain.ledger.entities import TransactionKind
from ...domain.receipts.model import (
    CARD,
    CASH,
    DOCUMENT_KIND_QUESTION,
    EARLIEST_RECEIPT,
    MANUAL,
    MAX_RECEIPT_TOTAL,
    PAYMENTS,
    RECEIPTS_VERSION,
    UNKNOWN_PAYMENT,
    DocumentKind,
    StoredReceipt,
    check,
    correct,
    date_of,
    kind_by_rules,
    match_charges,
    receipt_id,
    total_of,
)
from ...domain.shared.envelope import Caveat, Envelope, Fact
from ...domain.shared.hashing import content_id
from ..ports import (
    AuditLog,
    ClassifierUnavailable,
    Clock,
    DecisionModel,
    DecisionModelUnavailable,
    DocumentText,
    IdGenerator,
    ReceiptReader,
    ReceiptStore,
    SnapshotStore,
    StatementReaderUnavailable,
    StatementUnreadable,
    TransactionClassifier,
    TransactionStore,
)
from ..services.redaction import StatementRedactor
from .financial import FinancialUseCases
from .statements import ALLOWED_FILES, LOW_CONFIDENCE, MAX_STATEMENT_BYTES, StatementImport, StatementUseCases

logger = logging.getLogger(__name__)

MAX_DOCUMENT_BYTES = MAX_STATEMENT_BYTES
MIN_ROUTE_CONFIDENCE = 0.8  # below it a model's route is not taken: the user is asked for a clearer file
MAX_ROUTE_TEXT = 2000  # characters of redacted text a decision model sees
SPENDING_FACTS = ("spending.", "protected_surplus", "liquidity_floor")
LATEST_DOCUMENT = "latest-document"
RECEIPT_CAVEATS = frozenset({"RECEIPT_UNVERIFIED", "OCR_LOW_CONFIDENCE", "DUPLICATE_RECEIPT"})
EXPENSE = "expense"  # snapshot key prefix of an expense waiting for the user's confirmation
# What the copilot must ask when it could not tell: code, message, words its reply must contain (either language).
EXPENSE_ASK = {
    "payment": ("EXPENSE_PAYMENT_UNKNOWN", "Was it paid in cash or by card? A card purchase is matched with your statement later, so it is never counted twice; cash never reaches a statement.", ("cash", "card", "efectivo", "tarjeta")),
    "category": ("EXPENSE_CATEGORY_UNKNOWN", "What kind of spending was it (groceries, dining, transport, health...)? I could not tell its category from the description.", ("category", "categoría", "tipo de gasto")),
}
_CASH_WORDS = re.compile(r"\b(efectivo|cash|en billetes)\b", re.I)
_CARD_WORDS = re.compile(r"\b(tarjeta|d[eé]bito|cr[eé]dito|card|redcompra)\b", re.I)  # snapshot key of the user's last workflow (in memory, erased with the user)


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    """One step of the document workflow, for the UI. `value` is a label or a number as text, never prose."""

    key: str  # read | route | verify | redact | duplicate | categorize | match | spending | import
    status: str  # done | warning | skipped | failed
    value: str | None = None
    by: str | None = None  # the model or rule that answered, when one did
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class ReceiptView:
    receipt_id: str
    issuer: dict[str, str]  # {"untrusted_text": ...}
    issued_on: str | None
    total: int | None
    currency: str
    folio: str | None
    stamped: bool
    source: str
    category: str
    classifier: str
    verified: bool
    issues: tuple[dict[str, str], ...]
    matched_transaction: str | None  # the statement charge that records this purchase, if one does
    duplicate: bool
    counted: bool  # part of this cycle's logged spending: verified, not on a statement, dated inside the cycle
    corrected: bool  # the user typed or confirmed its total or date
    payment: str  # cash | card | unknown


@dataclass(frozen=True, slots=True)
class ExpenseProposal:
    """An expense the copilot prepared from what the user said. Nothing is stored until the user confirms it."""

    proposal_id: str
    amount: int  # one the user wrote: checked against their messages (rule 2)
    currency: str
    description: dict[str, str]  # {"untrusted_text": ...}: what it was, redacted
    spent_on: str
    category: str  # a CATEGORIES label, or 'uncategorized' when neither the user nor the classifier could tell
    payment: str  # cash | card | unknown: the user picks it in the card when they did not say it
    missing: tuple[str, ...]  # what the copilot must ask: payment, category


@dataclass(frozen=True, slots=True)
class DocumentIngest:
    kind: str  # statement | receipt | unknown
    steps: tuple[WorkflowStep, ...]
    statement: StatementImport | None
    receipt: ReceiptView | None
    spending: SpendingCheck | None


@dataclass(frozen=True, slots=True)
class SpendingStatus:
    check: SpendingCheck
    latest_receipt: ReceiptView | None
    receipts_counted: int  # verified receipts not yet on a statement, inside the cycle
    receipts_matched: int  # receipts a statement charge already records


class DocumentUseCases:
    def __init__(
        self,
        reader: ReceiptReader,
        redactor: StatementRedactor,
        statements: StatementUseCases,
        receipts: ReceiptStore,
        transactions: TransactionStore,
        classifier: TransactionClassifier,
        routers: Sequence[DecisionModel],
        financial: FinancialUseCases,
        audit: AuditLog,
        clock: Clock,
        ids: IdGenerator,
        snapshots: SnapshotStore,
    ) -> None:
        self._snapshots = snapshots
        self._reader = reader
        self._redactor = redactor
        self._statements = statements
        self._receipts = receipts
        self._transactions = transactions
        self._classifier = classifier
        self._routers = tuple(routers)
        self._financial = financial
        self._audit = audit
        self._clock = clock
        self._ids = ids

    # ---- the workflow ---------------------------------------------------------------------------

    def ingest(self, user_id: str, content: bytes, session_id: str = "documents", kind: str | None = None) -> Envelope[DocumentIngest]:
        """`kind` is the user's own answer ("receipt" or "statement") when the file could not be recognized: it
        replaces the routing, nothing else. Reading, checks and redaction are the same."""
        if not content:
            return Envelope.invalid("file", ALLOWED_FILES, params_version=RECEIPTS_VERSION, message="the file is empty")
        if len(content) > MAX_DOCUMENT_BYTES:
            return Envelope.invalid("file", ALLOWED_FILES, params_version=RECEIPTS_VERSION, message="the file is larger than 15 MB")
        try:
            peeked = self._reader.peek(content)
        except StatementUnreadable as exc:
            return Envelope.invalid("file", ALLOWED_FILES, params_version=RECEIPTS_VERSION, message=str(exc))
        except StatementReaderUnavailable as exc:
            return Envelope.insufficient(("document_reader",), params_version=RECEIPTS_VERSION, message=str(exc))

        if kind is not None:
            if kind not in (DocumentKind.RECEIPT.value, DocumentKind.STATEMENT.value):
                return Envelope.invalid("kind", ("receipt", "statement"), params_version=RECEIPTS_VERSION, message="kind must be receipt or statement")
            routed, by, confidence = DocumentKind(kind), "user", 1.0
        else:
            routed, by, confidence = self._route(peeked.format, peeked.text)
        result = self._run(user_id, content, session_id, peeked, routed, by, confidence)
        if result.ok and result.data is not None:
            self._snapshots.put(LATEST_DOCUMENT, user_id, result)  # what get_latest_document tells the copilot
        return result

    def _run(self, user_id: str, content: bytes, session_id: str, peeked: DocumentText, kind: DocumentKind, by: str, confidence: float) -> Envelope[DocumentIngest]:
        self._record(session_id, user_id, AuditKind.DOCUMENT_ROUTED, "ROUTED", f"kind={kind.value} by={by} confidence={confidence:.2f} format={peeked.format}")
        steps = [
            WorkflowStep("read", "done", peeked.format),
            WorkflowStep("route", "done" if kind is not DocumentKind.UNKNOWN else "failed", kind.value, by, round(confidence, 4)),
        ]
        if kind is DocumentKind.STATEMENT:
            return self._statement(user_id, content, session_id, steps)
        if kind is DocumentKind.RECEIPT:
            return self._receipt(user_id, content, session_id, steps)
        message = "this does not look like a bank statement or a receipt; try a clearer photo or the bank's own export"
        return Envelope.invalid("file", ("statement", "receipt"), params_version=RECEIPTS_VERSION, message=message)

    def _route(self, file_format: str, text: str) -> tuple[DocumentKind, str, float]:
        if file_format == "xlsx":
            return DocumentKind.STATEMENT, "format", 1.0
        by_rules = kind_by_rules(text)
        if by_rules is not None:
            return by_rules, "rules", 1.0
        state = self._redactor.redact_text(text)[0][:MAX_ROUTE_TEXT]  # personal data never leaves for a model
        for model in self._routers:
            try:
                judgment = model.judge(state, (DOCUMENT_KIND_QUESTION,)).get(DOCUMENT_KIND_QUESTION.key)
            except DecisionModelUnavailable:
                continue
            if judgment is None or judgment.label not in DOCUMENT_KIND_QUESTION.options:
                continue
            if judgment.confidence >= MIN_ROUTE_CONFIDENCE:
                return DocumentKind(judgment.label), judgment.source, judgment.confidence
            return DocumentKind.UNKNOWN, judgment.source, judgment.confidence
        return DocumentKind.UNKNOWN, "rules", 0.0

    def _statement(self, user_id: str, content: bytes, session_id: str, steps: list[WorkflowStep]) -> Envelope[DocumentIngest]:
        result = self._statements.import_statement(user_id, content, session_id)
        if not result.ok or result.data is None:
            return replace(result, data=None)  # type: ignore[arg-type]
        for item in result.data.imports:
            verified = item.statement.verified
            steps.append(WorkflowStep("verify", "done" if verified else "warning", "verified" if verified else "unverified"))
            if item.redaction is not None:
                steps.append(WorkflowStep("redact", "done", str(sum(item.redaction.counts.values()))))
            steps.append(WorkflowStep("duplicate", "warning" if item.duplicate else "done", "duplicate" if item.duplicate else "new"))
            ledger = item.ledger
            if item.statement.provisional:  # unbilled card movements: the billed statement adds them, so they are never posted twice
                steps.append(WorkflowStep("categorize", "skipped", "provisional"))
            elif not verified:
                steps.append(WorkflowStep("categorize", "skipped", "unverified"))
            else:
                steps.append(WorkflowStep("categorize", "done" if ledger.posted else "skipped", str(ledger.posted), ledger.classifier))
        spending = self.spending_status(user_id)
        if spending.ok and spending.data is not None:
            steps.append(WorkflowStep("spending", "done", str(spending.data.check.per_day)))
        data = DocumentIngest("statement", tuple(steps), result.data, None, spending.data.check if spending.ok and spending.data else None)
        return replace(
            result,  # type: ignore[arg-type]
            data=data,
            facts=(*result.facts, *(spending.facts if spending.ok else ())),
            warnings=(*result.warnings, *(w for w in spending.warnings if w not in result.warnings)),
        )

    def _receipt(self, user_id: str, content: bytes, session_id: str, steps: list[WorkflowStep]) -> Envelope[DocumentIngest]:
        try:
            read = self._reader.read_receipt(content)
        except StatementUnreadable as exc:
            return Envelope.invalid("file", ALLOWED_FILES, params_version=RECEIPTS_VERSION, message=str(exc))
        except StatementReaderUnavailable as exc:
            return Envelope.insufficient(("document_reader",), params_version=RECEIPTS_VERSION, message=str(exc))

        today = self._clock.now().date()
        rid = receipt_id(user_id, read)
        stored = self._receipts.get(user_id, rid)
        duplicate = stored is not None
        if stored is None:
            issuer_text = read.issuer or (read.stamp.issuer_name if read.stamp and read.stamp.issuer_name else "")
            # Personal data is removed before anything is stored or classified (ADR-028): rules, then the detector if set.
            issuer, _ = self._redactor.redact_text(sanitize(issuer_text))
            category, classifier, category_confidence = self._categorize(issuer, read.stamp.first_item if read.stamp else None)
            stored = StoredReceipt(
                receipt_id=rid,
                user_id=user_id,
                imported_at=self._clock.now(),
                issuer=issuer,
                issued_on=date_of(read),
                total=total_of(read),
                currency="CLP",
                folio=read.folio or (str(read.stamp.folio) if read.stamp else None),
                stamped=read.stamp is not None,
                source=read.source,
                confidence=read.confidence,
                category=category,
                classifier=classifier,
                category_confidence=category_confidence,
                issues=check(read, today),
            )
            if not self._receipts.add(stored):  # the same receipt was imported concurrently
                stored, duplicate = self._receipts.get(user_id, rid) or stored, True

        matched = match_charges((stored,), self._transactions.for_user(user_id)).get(stored.receipt_id)
        self._record(
            session_id, user_id, AuditKind.RECEIPT_IMPORTED,
            "DUPLICATE" if duplicate else ("VERIFIED" if stored.verified else "UNVERIFIED"),
            f"source={stored.source} stamped={stored.stamped} issues={','.join(i.code.value for i in stored.issues) or 'none'} "
            f"category={stored.category} classifier={stored.classifier} matched={'yes' if matched else 'no'} reader={self._reader.name}",
            snapshot=stored.receipt_id,
        )
        spending = self.spending_status(user_id)
        check_result = spending.data.check if spending.ok and spending.data is not None else None
        counted = _counted(stored, matched, check_result)
        view = _receipt_view(stored, matched, duplicate, counted)
        steps += [
            WorkflowStep("verify", "done" if stored.verified else "warning", "stamp" if stored.stamped and stored.verified else ("verified" if stored.verified else stored.issues[0].code.value)),
            WorkflowStep("redact", "done", None, self._redactor.detector if self._redactor.detector != "none" else "rules"),
            WorkflowStep("duplicate", "warning" if duplicate else "done", "duplicate" if duplicate else "new"),
            WorkflowStep("categorize", "done" if stored.category != UNCATEGORIZED else "warning", stored.category, stored.classifier, stored.category_confidence),
            _match_step(stored, matched, counted, check_result),
        ]
        warnings = list(_receipt_caveats(stored, duplicate))
        facts = list(_receipt_facts(stored))
        if check_result is not None:
            steps.append(WorkflowStep("spending", "done", str(check_result.per_day)))
            facts += [f for f in spending.facts if f not in facts]
            warnings += [w for w in spending.warnings if w not in warnings]
        else:
            steps.append(WorkflowStep("spending", "skipped"))
        return Envelope.success(
            DocumentIngest("receipt", tuple(steps), None, view, check_result),
            params_version=RECEIPTS_VERSION,
            snapshot_id=stored.receipt_id,
            as_of=today.isoformat(),
            facts=tuple(facts),
            warnings=tuple(warnings),
        )

    def _categorize(self, issuer: str, first_item: str | None) -> tuple[str, str, float | None]:
        # The store says what kind of spending it is; an item is only a hint when the store's name could not be read.
        description = (issuer or first_item or "").strip()
        if not description:
            return UNCATEGORIZED, self._classifier.name, None
        try:
            guesses = list(self._classifier.classify([description]))
        except ClassifierUnavailable:
            return UNCATEGORIZED, "none", None
        if len(guesses) != 1:
            return UNCATEGORIZED, self._classifier.name, None
        guess = guesses[0]
        return accept(guess), guess.source or self._classifier.name, guess.confidence

    # ---- what the copilot is told (tools get_latest_document and get_spending_status, T0) -----------

    def latest_document(self, user_id: str) -> Envelope[DocumentIngest]:
        """The workflow of the last file this user dropped, as it answered then: the copilot explains it from this."""
        stored = self._snapshots.get(LATEST_DOCUMENT, user_id)
        if not isinstance(stored, Envelope) or stored.data is None:
            return Envelope.insufficient(("document",), params_version=RECEIPTS_VERSION, message="the user has not added a document yet")
        # The document only: the spending check-in of that moment is stale, and get_spending_status gives today's.
        latest = replace(
            stored,
            data=replace(stored.data, spending=None, steps=tuple(s for s in stored.data.steps if s.key != "spending")),
            facts=tuple(f for f in stored.facts if not f.key.startswith(SPENDING_FACTS)),
            warnings=tuple(w for w in stored.warnings if not w.code.startswith("SPENDING_")),
        )
        if latest.data is None or latest.data.receipt is None:
            return latest
        # A receipt the user corrected since: what it says now, not what the reader read then.
        now = self._receipt_now(user_id, latest.data.receipt.receipt_id, duplicate=latest.data.receipt.duplicate)
        if now is None:
            return latest
        view, caveats, facts = now
        return replace(
            latest,
            data=replace(latest.data, receipt=view),
            facts=(*(f for f in latest.facts if not f.key.startswith("receipt.")), *facts),
            warnings=(*(w for w in latest.warnings if w.code not in RECEIPT_CAVEATS), *caveats),
        )

    def _receipt_now(self, user_id: str, receipt_id: str, *, duplicate: bool) -> tuple[ReceiptView, tuple[Caveat, ...], tuple[Fact, ...]] | None:
        stored = self._receipts.get(user_id, receipt_id)
        if stored is None:
            return None
        matched = match_charges(self._receipts.for_user(user_id), self._transactions.for_user(user_id)).get(receipt_id)
        status = self.spending_status(user_id)
        check_result = status.data.check if status.ok and status.data is not None else None
        view = _receipt_view(stored, matched, duplicate, _counted(stored, matched, check_result))
        return view, _receipt_caveats(stored, duplicate), _receipt_facts(stored)

    # ---- expenses the user tells the copilot about ------------------------------------------------------

    def propose_expense(
        self, user_id: str, user_text: str, amount: object, description: object = None, category: object = None,
        payment: object = None, spent_on: object = None,
    ) -> Envelope[ExpenseProposal]:
        """Prepare, never store, an expense the user said they made (tool propose_expense, T1, stateful).

        The amount must be one the user wrote in their last messages; otherwise the copilot must ask for it. The
        category is the user's word when it is a known one, else the classifier's gated guess on the description;
        the payment is cash or card only when the user said so. What is still unknown is listed in `missing`, so the
        copilot asks, and the user completes and confirms it in the card. The date defaults to today.
        """
        version = RECEIPTS_VERSION
        if isinstance(amount, bool) or not isinstance(amount, int) or not 0 < amount <= MAX_RECEIPT_TOTAL:
            return Envelope.invalid("amount", ("amount",), params_version=version, message="ask the user how much they spent")
        if amount not in written_amounts(user_text):
            return Envelope.invalid("amount", ("amount",), params_version=version, message="the amount must be one the user wrote; ask the user for it")
        today = self._clock.now().date()
        try:
            day = _parse_date(spent_on) or today
        except ValueError as exc:
            return Envelope.invalid("spent_on", ("spent_on",), params_version=version, message=str(exc))
        if not EARLIEST_RECEIPT <= day <= today:
            return Envelope.invalid("spent_on", ("spent_on",), params_version=version, message="the date must be a past day, from 2000 on")
        text = redact_text_safe(self._redactor, str(description or ""))
        label = str(category) if isinstance(category, str) and category in CATEGORIES else None
        if label is None:
            label, _, _ = self._categorize(text, None)
        paid = str(payment) if payment in PAYMENTS else UNKNOWN_PAYMENT
        if paid == UNKNOWN_PAYMENT or not _said_payment(user_text, paid):
            paid = _payment_said(user_text)
        missing = tuple(m for m, unknown in (("payment", paid == UNKNOWN_PAYMENT), ("category", label == UNCATEGORIZED)) if unknown)
        proposal = ExpenseProposal(
            proposal_id=self._ids.new("exp"), amount=amount, currency="CLP", description=wrap_untrusted(text),
            spent_on=day.isoformat(), category=label, payment=paid, missing=missing,
        )
        self._snapshots.put(f"{EXPENSE}:{proposal.proposal_id}", user_id, proposal)
        facts = (Fact("expense.amount", amount, "CLP", "the amount the user said"), Fact("expense.spent_on", day.isoformat(), "date", "when it was spent"))
        caveats = tuple(Caveat(EXPENSE_ASK[m][0], EXPENSE_ASK[m][1], EXPENSE_ASK[m][2]) for m in missing)
        return Envelope.success(proposal, params_version=version, snapshot_id=proposal.proposal_id, as_of=today.isoformat(), facts=facts, warnings=caveats)

    def confirm_expense(
        self, user_id: str, session_id: str, proposal_id: str, payment: object = None, category: object = None, spent_on: object = None
    ) -> Envelope[ReceiptView]:
        """The user confirms the expense in the app, completing what was missing. The amount is the proposal's."""
        proposal = self._snapshots.get(f"{EXPENSE}:{proposal_id}", user_id)
        if not isinstance(proposal, ExpenseProposal):
            return Envelope.insufficient(("expense",), params_version=RECEIPTS_VERSION, message="no such expense to confirm")
        paid = str(payment) if payment in PAYMENTS else proposal.payment
        if paid not in PAYMENTS:
            return Envelope.invalid("payment", PAYMENTS, params_version=RECEIPTS_VERSION, message="say whether it was cash or card")
        label = str(category) if isinstance(category, str) and category in CATEGORIES else proposal.category
        today = self._clock.now().date()
        try:
            day = _parse_date(spent_on) or date.fromisoformat(proposal.spent_on)
        except ValueError as exc:
            return Envelope.invalid("spent_on", ("spent_on",), params_version=RECEIPTS_VERSION, message=str(exc))
        if not EARLIEST_RECEIPT <= day <= today:
            return Envelope.invalid("spent_on", ("spent_on",), params_version=RECEIPTS_VERSION, message="the date must be a past day, from 2000 on")
        stored = StoredReceipt(
            # The expense, not the card: two cards prepared for the same words, amount and day are one expense.
            receipt_id=content_id("rcpt", user_id, MANUAL, proposal.amount, day.isoformat(), proposal.description["untrusted_text"].casefold()),
            user_id=user_id, imported_at=self._clock.now(),
            issuer=proposal.description["untrusted_text"], issued_on=day, total=proposal.amount, currency=proposal.currency, folio=None,
            stamped=False, source=MANUAL, confidence=None, category=label, classifier="user" if category in CATEGORIES else "copilot",
            category_confidence=None, issues=(), corrected=False, payment=paid,
        )
        if not self._receipts.add(stored):
            return Envelope.invalid("proposal_id", (), params_version=RECEIPTS_VERSION, message="this expense was already confirmed")
        self._snapshots.put(f"{EXPENSE}:{proposal_id}", user_id, None)  # single use
        self._record(session_id, user_id, AuditKind.EXPENSE_LOGGED, "LOGGED", f"payment={paid} category={label} source=manual", snapshot=stored.receipt_id)
        view, caveats, facts = self._receipt_now(user_id, stored.receipt_id, duplicate=False) or (None, (), ())
        assert view is not None
        return Envelope.success(view, params_version=RECEIPTS_VERSION, snapshot_id=stored.receipt_id, as_of=today.isoformat(), facts=facts, warnings=caveats)

    # ---- corrections: the user's, never a model's ---------------------------------------------------

    def correct_receipt(
        self, user_id: str, session_id: str, receipt_id: str, total: object = None, issued_on: object = None
    ) -> Envelope[ReceiptView]:
        """The user types the total or the date the reader could not read (or confirms a doubtful one). No agent tool
        reaches this: the copilot only asks, and the app's form sends what the user typed (rules 2 and 3)."""
        stored = self._receipts.get(user_id, receipt_id)
        if stored is None:
            return Envelope.insufficient(("receipt",), params_version=RECEIPTS_VERSION, message="no such receipt for this user")
        try:
            new_total = _parse_total(total)
            new_date = _parse_date(issued_on)
            corrected = correct(stored, new_total, new_date, self._clock.now().date())
        except ValueError as exc:
            field = "total" if "total" in str(exc) else "issued_on"
            return Envelope.invalid(field, ("total", "issued_on"), params_version=RECEIPTS_VERSION, message=str(exc))
        self._receipts.replace(corrected)
        fields = ",".join(name for name, value in (("total", new_total), ("issued_on", new_date)) if value is not None)
        self._record(
            session_id, user_id, AuditKind.RECEIPT_CORRECTED, "VERIFIED" if corrected.verified else "UNVERIFIED",
            f"fields={fields} issues={','.join(i.code.value for i in corrected.issues) or 'none'}", snapshot=receipt_id,
        )
        view, caveats, facts = self._receipt_now(user_id, receipt_id, duplicate=False) or (None, (), ())
        assert view is not None  # replaced just above
        return Envelope.success(
            view,
            params_version=RECEIPTS_VERSION,
            snapshot_id=content_id("rcpt-correction", receipt_id, view.total, view.issued_on),
            as_of=self._clock.now().date().isoformat(),
            facts=facts,
            warnings=caveats,
        )

    def spending_status(self, user_id: str) -> Envelope[SpendingStatus]:
        receipts = self._receipts.for_user(user_id)
        transactions = self._transactions.for_user(user_id)
        matched = match_charges(receipts, transactions)
        logged = [
            LoggedSpend(r.issued_on, r.total, r.category, "receipt", r.receipt_id)
            for r in receipts
            if r.verified and r.total is not None and r.issued_on is not None and r.receipt_id not in matched
        ]
        logged += [_charge(p) for p in transactions if _is_charge(p)]
        result = self._financial.spending_check(user_id, logged, self._clock.now().date())
        if not result.ok or result.data is None:
            return replace(result, data=None)  # type: ignore[arg-type]
        check_result = result.data
        counted = sum(
            1 for item in logged if item.source == "receipt" and check_result.window_start <= item.on <= check_result.window_end
        )
        latest = receipts[-1] if receipts else None
        latest_view = None
        if latest is not None:
            latest_matched = matched.get(latest.receipt_id)
            latest_view = _receipt_view(latest, latest_matched, False, _counted(latest, latest_matched, check_result))
        facts = [*result.facts, Fact("spending.receipts_counted", counted, "count", "verified receipts not yet on a statement, this cycle")]
        if latest is not None:
            facts += _receipt_facts(latest)
        return Envelope.success(
            SpendingStatus(check_result, latest_view, counted, len(matched)),
            params_version=result.params_version,
            snapshot_id=content_id("spending-status", result.snapshot_id, sorted(matched.items())),
            as_of=result.as_of or "",
            facts=tuple(facts),
            warnings=result.warnings,
        )

    def list_receipts(self, user_id: str) -> Envelope[tuple[ReceiptView, ...]]:
        receipts = self._receipts.for_user(user_id)
        matched = match_charges(receipts, self._transactions.for_user(user_id))
        status = self.spending_status(user_id)
        check_result = status.data.check if status.ok and status.data is not None else None
        views = tuple(_receipt_view(r, matched.get(r.receipt_id), False, _counted(r, matched.get(r.receipt_id), check_result)) for r in receipts)
        return Envelope.success(
            views,
            params_version=RECEIPTS_VERSION,
            snapshot_id=content_id("rcpts", user_id, [v.receipt_id for v in views], sorted(matched.items())),
            as_of=self._clock.now().date().isoformat(),
            facts=(Fact(f"{user_id}.receipts", len(views), "count", "receipts stored for the user"),),
        )

    def _record(self, session_id: str, user_id: str, kind: AuditKind, result: str, detail: str, *, snapshot: str | None = None) -> None:
        self._audit.append(
            AuditDraft(
                event_id=self._ids.new("evt"),
                timestamp=self._clock.now(),
                session_id=session_id,
                user_id=user_id,
                actor=Actor.USER,
                kind=kind,
                forecast_snapshot_id=snapshot,
                policy_version=RECEIPTS_VERSION,
                execution_result=result,
                detail=detail,
            )
        )


def _payment_said(text: str) -> str:
    """Cash or card only when the user's words say it; both or neither is unknown, and the copilot asks."""
    cash, card = bool(_CASH_WORDS.search(text)), bool(_CARD_WORDS.search(text))
    return CASH if cash and not card else CARD if card and not cash else UNKNOWN_PAYMENT


def _said_payment(text: str, payment: str) -> bool:
    return _payment_said(text) == payment


def redact_text_safe(redactor: StatementRedactor, text: str) -> str:
    """The description as it may be stored and shown: control characters out, personal data masked (ADR-028)."""
    return redactor.redact_text(sanitize(text))[0] if text.strip() else ""


def _parse_total(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("the total must be a whole number of pesos")
    return value


def _parse_date(value: object) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError("the date must be YYYY-MM-DD") from exc


def _is_charge(p: PostedTransaction) -> bool:
    return p.transaction.kind in (TransactionKind.PURCHASE, TransactionKind.FEE) and p.transaction.amount < 0


def _charge(p: PostedTransaction) -> LoggedSpend:
    return LoggedSpend(p.transaction.date, -p.transaction.amount, p.transaction.category, "statement", p.transaction.txn_id)


def _counted(r: StoredReceipt, matched: str | None, check: SpendingCheck | None) -> bool:
    """Whether this receipt is part of this cycle's logged spending: verified, not on a statement, dated inside it."""
    if check is None or not r.verified or matched or r.issued_on is None:
        return False
    return check.window_start <= r.issued_on <= check.window_end


def _match_step(r: StoredReceipt, matched: str | None, counted: bool, check: SpendingCheck | None) -> WorkflowStep:
    if matched:
        return WorkflowStep("match", "done", "matched")
    if counted:
        return WorkflowStep("match", "done", "pending")
    if r.verified and check is not None:
        return WorkflowStep("match", "skipped", "outside")  # dated before (or after) the cycle the check-in is about
    return WorkflowStep("match", "skipped")


def _receipt_view(r: StoredReceipt, matched: str | None, duplicate: bool, counted: bool) -> ReceiptView:
    return ReceiptView(
        receipt_id=r.receipt_id,
        issuer=wrap_untrusted(r.issuer),
        issued_on=r.issued_on.isoformat() if r.issued_on else None,
        total=r.total,
        currency=r.currency,
        folio=r.folio,
        stamped=r.stamped,
        source=r.source,
        category=r.category,
        classifier=r.classifier,
        verified=r.verified,
        issues=tuple({"code": i.code.value, "message": i.message} for i in r.issues),
        matched_transaction=matched,
        duplicate=duplicate,
        counted=counted,
        corrected=r.corrected,
        payment=r.payment,
    )


def _receipt_facts(r: StoredReceipt) -> tuple[Fact, ...]:
    facts = []
    if r.total is not None:
        facts.append(Fact("receipt.total", r.total, r.currency, "the receipt's total, as read (confirmed by the SII stamp when stamped)"))
    if r.issued_on is not None:
        facts.append(Fact("receipt.issued_on", r.issued_on.isoformat(), "date", "the receipt's date"))
    return tuple(facts)


def _receipt_caveats(r: StoredReceipt, duplicate: bool) -> tuple[Caveat, ...]:
    caveats = []
    if not r.verified:
        codes = ", ".join(sorted({i.code.value for i in r.issues}))
        caveats.append(Caveat("RECEIPT_UNVERIFIED", f"The receipt was stored but could not be verified ({codes}); it is not counted.", ("not counted", "no se cuenta", "no se contó", "no la cuento", "no se está contando")))
    elif r.source == "ocr" and not r.stamped and not r.corrected and r.confidence is not None and r.confidence < LOW_CONFIDENCE:
        caveats.append(Caveat("OCR_LOW_CONFIDENCE", "The receipt's total was read by OCR with low confidence and no SII stamp confirms it.", ("OCR",)))
    if duplicate:
        caveats.append(Caveat("DUPLICATE_RECEIPT", "This receipt was already imported; it is counted once.", ("already imported", "ya estaba", "ya se había", "una sola vez", "una vez")))
    return tuple(caveats)
