"""Import bank statements (cartolas) and read them back.

Import = read (adapter, may misread) → redact personal data (domain rules + optional detector) →
reconcile (domain, deterministic) → store → post to the transaction ledger (classified charges) → audit.
The statement as read lives only in memory during the import: from redaction on, everything works on
the clean copy (ADR-028). If redaction fails, the import is rejected and nothing is stored.
A statement that does not add up is still stored, marked unverified, with a warning that names
every issue: its amounts are evidence, never authority, so it is not posted. Re-importing the
same statement stores nothing new. Descriptions leave this layer wrapped as untrusted text.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ...domain.agent.untrusted import wrap_untrusted
from ...domain.audit.events import Actor, AuditDraft, AuditKind
from ...domain.shared.envelope import Caveat, Envelope, Fact
from ...domain.shared.hashing import content_id
from ...domain.statements.model import STATEMENTS_VERSION, Issue, StoredStatement, reconcile
from ..ports import (
    AuditLog,
    Clock,
    IdGenerator,
    StatementReader,
    StatementReaderUnavailable,
    StatementStore,
    StatementUnreadable,
)
from ..services.posting import LedgerPosting, PostingResult
from ..services.redaction import RedactionReport, StatementRedactor

logger = logging.getLogger(__name__)

MAX_STATEMENT_BYTES = 15 * 1024 * 1024
# Below this, an OCR'd line gets a warning. It never marks the statement unverified: amounts and dates are
# verified by reconciliation, and EasyOCR reports low confidence on correct digits with noisy separators.
# What reconciliation cannot check is the description text, which is what the warning is about.
LOW_CONFIDENCE = 0.5
ALLOWED_FILES = ("pdf", "image")


@dataclass(frozen=True, slots=True)
class IssueView:
    code: str
    message: str
    expected: int | None
    found: int | None
    on: str | None


@dataclass(frozen=True, slots=True)
class StatementSummaryView:
    statement_id: str
    bank: str
    account_ref: str
    currency: str
    period_start: str
    period_end: str
    source: str
    imported_at: str
    line_count: int
    total_debits: int  # computed from the lines, positive magnitude
    total_credits: int
    opening_balance: int | None  # as printed
    closing_balance: int | None
    verified: bool
    issues: tuple[IssueView, ...]


@dataclass(frozen=True, slots=True)
class LedgerPostingView:
    posted: int  # transactions this statement contributes to the ledger (0 when not posted)
    new: int  # of those, added by this import
    uncategorized: int
    classifier: str | None


@dataclass(frozen=True, slots=True)
class StatementImport:
    duplicate: bool
    statement: StatementSummaryView
    ledger: LedgerPostingView


@dataclass(frozen=True, slots=True)
class LineView:
    index: int
    posted_on: str
    description: dict[str, str]  # {"untrusted_text": ...}
    amount: int
    reference: str | None
    branch: str | None
    confidence: float | None


@dataclass(frozen=True, slots=True)
class DailyBalanceView:
    on: str
    balance: int


@dataclass(frozen=True, slots=True)
class StatementDetail:
    statement: StatementSummaryView
    lines: tuple[LineView, ...]
    daily_balances: tuple[DailyBalanceView, ...]


class StatementUseCases:
    def __init__(
        self,
        reader: StatementReader,
        redactor: StatementRedactor,
        store: StatementStore,
        posting: LedgerPosting,
        audit: AuditLog,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._reader = reader
        self._redactor = redactor
        self._store = store
        self._posting = posting
        self._audit = audit
        self._clock = clock
        self._ids = ids

    def import_statement(self, user_id: str, content: bytes, session_id: str = "statements") -> Envelope[StatementImport]:
        if not content:
            return Envelope.invalid("file", ALLOWED_FILES, params_version=STATEMENTS_VERSION, message="the file is empty")
        if len(content) > MAX_STATEMENT_BYTES:
            return Envelope.invalid("file", ALLOWED_FILES, params_version=STATEMENTS_VERSION, message="the file is larger than 15 MB")
        try:
            read = self._reader.read(content)
        except StatementUnreadable as exc:
            return Envelope.invalid("file", ALLOWED_FILES, params_version=STATEMENTS_VERSION, message=str(exc))
        except StatementReaderUnavailable as exc:
            return Envelope.insufficient(("statement_reader",), params_version=STATEMENTS_VERSION, message=str(exc))

        # The id hashes the statement as read, so a cartola imported again is a duplicate whatever the rules mask (ADR-028).
        statement_id = content_id("stmt", user_id, read.bank, read.account_ref, read.period_start, read.period_end, read.lines)
        stored = self._store.get(user_id, statement_id)
        redaction: RedactionReport | None = None  # stays None for a duplicate: nothing new is redacted or stored
        if stored is None:
            try:
                statement, redaction = self._redactor.redact(read)
            except Exception as exc:  # fail closed: a statement that could not be redacted is never stored
                # The error's type only: its message could quote the statement.
                logger.error("statement redaction failed (%s): the import was rejected and nothing was stored", type(exc).__name__)
                message = "personal data could not be removed from the statement, so it was not stored"
                return Envelope.insufficient(("redaction",), params_version=STATEMENTS_VERSION, message=message)
            stored = StoredStatement(statement_id, user_id, self._clock.now(), statement, reconcile(statement).issues)
            if not self._store.add(stored):  # the same statement was imported concurrently
                stored, redaction = self._store.get(user_id, statement_id) or stored, None
        duplicate = redaction is None
        posting = self._posting.post(stored)

        self._audit.append(
            AuditDraft(
                event_id=self._ids.new("evt"),
                timestamp=self._clock.now(),
                session_id=session_id,
                user_id=user_id,
                actor=Actor.USER,
                kind=AuditKind.STATEMENT_IMPORTED,
                forecast_snapshot_id=statement_id,
                policy_version=STATEMENTS_VERSION,
                execution_result="DUPLICATE" if duplicate else ("VERIFIED" if stored.verified else "UNVERIFIED"),
                detail=(
                    f"bank={stored.statement.bank} lines={len(stored.statement.lines)} "
                    f"issues={','.join(i.code.value for i in stored.issues) or 'none'} {_redaction_detail(redaction)}"
                    f"posted={posting.posted} new={posting.new} uncategorized={posting.uncategorized} classifier={posting.classifier or 'none'}"
                ),
            )
        )

        summary = _summary(stored)
        warnings = [*_unverified(stored), *_low_confidence(stored), *_degraded(redaction), *posting.warnings]
        if duplicate:
            warnings.append(Caveat("DUPLICATE_STATEMENT", "This statement was already imported; nothing new was stored.", ("already imported",)))
        return Envelope.success(
            StatementImport(duplicate, summary, _ledger_view(posting)),
            params_version=STATEMENTS_VERSION,
            snapshot_id=statement_id,
            as_of=summary.period_end,
            facts=(*_facts(summary), *_posting_facts(summary.statement_id, posting)),
            warnings=tuple(warnings),
        )

    def list_statements(self, user_id: str) -> Envelope[tuple[StatementSummaryView, ...]]:
        views = tuple(_summary(s) for s in self._store.for_user(user_id))
        return Envelope.success(
            views,
            params_version=STATEMENTS_VERSION,
            snapshot_id=content_id("stmts", user_id, [v.statement_id for v in views]),
            as_of=max((v.period_end for v in views), default=""),
            facts=(Fact(f"{user_id}.statements", len(views), "count", "statements stored for the user"),),
        )

    def get_statement(self, user_id: str, statement_id: str) -> Envelope[StatementDetail]:
        stored = self._store.get(user_id, statement_id)
        if stored is None:
            return Envelope.insufficient(("statement",), params_version=STATEMENTS_VERSION, message="no such statement for this user")
        summary = _summary(stored)
        detail = StatementDetail(
            summary,
            tuple(
                LineView(line.index, line.posted_on.isoformat(), wrap_untrusted(line.description), line.amount, line.reference, line.branch, line.confidence)
                for line in stored.statement.lines
            ),
            tuple(DailyBalanceView(b.on.isoformat(), b.balance) for b in stored.statement.daily_balances),
        )
        return Envelope.success(
            detail,
            params_version=STATEMENTS_VERSION,
            snapshot_id=stored.statement_id,
            as_of=summary.period_end,
            facts=_facts(summary),
            warnings=(*_unverified(stored), *_low_confidence(stored)),
        )


def _unverified(stored: StoredStatement) -> tuple[Caveat, ...]:
    if stored.verified:
        return ()
    codes = ", ".join(sorted({i.code.value for i in stored.issues}))
    return (
        Caveat(
            "STATEMENT_UNVERIFIED",
            f"The statement was stored but does not reconcile ({codes}); its amounts are unverified.",
            ("unverified", "does not reconcile"),
        ),
    )


def _low_confidence(stored: StoredStatement) -> tuple[Caveat, ...]:
    shaky = [line for line in stored.statement.lines if line.confidence is not None and line.confidence < LOW_CONFIDENCE]
    if not shaky:
        return ()
    return (
        Caveat(
            "OCR_LOW_CONFIDENCE",
            f"{len(shaky)} of {len(stored.statement.lines)} lines were read by OCR with low confidence; amounts are checked "
            "by reconciliation, but their descriptions may contain misread characters.",
            ("OCR", "misread"),
        ),
    )


def _degraded(redaction: RedactionReport | None) -> tuple[Caveat, ...]:
    if redaction is None or not redaction.degraded:
        return ()
    return (
        Caveat(
            "REDACTION_DEGRADED",
            f"Personal data was removed by the built-in rules only, because the detector {redaction.detector} was unavailable; "
            "a name outside a transfer line may remain in the descriptions.",
            ("personal data", "rules only"),
        ),
    )


def _redaction_detail(redaction: RedactionReport | None) -> str:
    """Audit detail: how much was masked and by what, never what (ADR-028). Empty for a duplicate, which redacts nothing."""
    if redaction is None:
        return ""
    return f"redacted={redaction.masked} detector={redaction.detector} {'degraded=yes ' if redaction.degraded else ''}"


def _ledger_view(p: PostingResult) -> LedgerPostingView:
    return LedgerPostingView(p.posted, p.new, p.uncategorized, p.classifier)


def _posting_facts(statement_id: str, p: PostingResult) -> tuple[Fact, ...]:
    key = f"statement.{statement_id}.ledger"
    return (
        Fact(f"{key}.posted", p.posted, "count", "transactions this statement contributes to the ledger"),
        Fact(f"{key}.uncategorized", p.uncategorized, "count", "charges whose category was not accepted"),
    )


def _issue_view(issue: Issue) -> IssueView:
    return IssueView(issue.code.value, issue.message, issue.expected, issue.found, issue.on.isoformat() if issue.on else None)


def _summary(stored: StoredStatement) -> StatementSummaryView:
    s = stored.statement
    return StatementSummaryView(
        statement_id=stored.statement_id,
        bank=s.bank,
        account_ref=s.account_ref,
        currency=s.currency,
        period_start=s.period_start.isoformat(),
        period_end=s.period_end.isoformat(),
        source=s.source,
        imported_at=stored.imported_at.isoformat(),
        line_count=len(s.lines),
        total_debits=-sum(line.amount for line in s.lines if line.amount < 0),
        total_credits=sum(line.amount for line in s.lines if line.amount > 0),
        opening_balance=s.summary.opening_balance if s.summary else None,
        closing_balance=s.summary.closing_balance if s.summary else None,
        verified=stored.verified,
        issues=tuple(_issue_view(i) for i in stored.issues),
    )


def _facts(v: StatementSummaryView) -> tuple[Fact, ...]:
    key = f"statement.{v.statement_id}"
    facts = [
        Fact(f"{key}.lines", v.line_count, "count", "movements read from the statement"),
        Fact(f"{key}.total_debits", v.total_debits, v.currency, "sum of charges read from the lines"),
        Fact(f"{key}.total_credits", v.total_credits, v.currency, "sum of deposits read from the lines"),
    ]
    for name, value in (("opening_balance", v.opening_balance), ("closing_balance", v.closing_balance)):
        if value is not None:
            facts.append(Fact(f"{key}.{name}", value, v.currency, "as printed on the statement"))
    return tuple(facts)
