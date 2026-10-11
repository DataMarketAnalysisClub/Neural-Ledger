"""Import bank statements (cartolas) and read them back.

Import = read (adapter, may misread) → reconcile (domain, deterministic) → store → audit.
A statement that does not add up is still stored, marked unverified, with a warning that names
every issue: its amounts are evidence, never authority. Re-importing the same statement stores
nothing new. Descriptions leave this layer wrapped as untrusted text.
"""

from __future__ import annotations

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

MAX_STATEMENT_BYTES = 15 * 1024 * 1024
MIN_CONFIDENCE = 0.6  # OCR cells read below this mark the statement unverified even if it adds up
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
class StatementImport:
    duplicate: bool
    statement: StatementSummaryView


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
    def __init__(self, reader: StatementReader, store: StatementStore, audit: AuditLog, clock: Clock, ids: IdGenerator) -> None:
        self._reader = reader
        self._store = store
        self._audit = audit
        self._clock = clock
        self._ids = ids

    def import_statement(self, user_id: str, content: bytes, session_id: str = "statements") -> Envelope[StatementImport]:
        if not content:
            return Envelope.invalid("file", ALLOWED_FILES, params_version=STATEMENTS_VERSION, message="the file is empty")
        if len(content) > MAX_STATEMENT_BYTES:
            return Envelope.invalid("file", ALLOWED_FILES, params_version=STATEMENTS_VERSION, message="the file is larger than 15 MB")
        try:
            statement = self._reader.read(content)
        except StatementUnreadable as exc:
            return Envelope.invalid("file", ALLOWED_FILES, params_version=STATEMENTS_VERSION, message=str(exc))
        except StatementReaderUnavailable as exc:
            return Envelope.insufficient(("statement_reader",), params_version=STATEMENTS_VERSION, message=str(exc))

        issues = reconcile(statement, min_confidence=MIN_CONFIDENCE).issues
        statement_id = content_id(
            "stmt", user_id, statement.bank, statement.account_ref, statement.period_start, statement.period_end, statement.lines
        )
        stored = StoredStatement(statement_id, user_id, self._clock.now(), statement, issues)
        duplicate = not self._store.add(stored)
        if duplicate:
            stored = self._store.get(user_id, statement_id) or stored

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
                detail=f"bank={statement.bank} lines={len(statement.lines)} issues={','.join(i.code.value for i in stored.issues) or 'none'}",
            )
        )

        summary = _summary(stored)
        warnings = list(_unverified(stored))
        if duplicate:
            warnings.append(Caveat("DUPLICATE_STATEMENT", "This statement was already imported; nothing new was stored.", ("already imported",)))
        return Envelope.success(
            StatementImport(duplicate, summary),
            params_version=STATEMENTS_VERSION,
            snapshot_id=statement_id,
            as_of=summary.period_end,
            facts=_facts(summary),
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
            warnings=_unverified(stored),
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
