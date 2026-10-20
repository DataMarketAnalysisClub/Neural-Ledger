"""Investments the user holds at a provider (ADR-044, Role C): statements the user imports, an account linked at the
provider, and the read the agent uses.

Importing a statement is the path in use: the user downloads Fintual's investment statement and transactions
certificate and drops them in the app (or on the copilot, which routes them here). A reader adapter extracts the rows,
never the holder's name or RUT; the domain checks that they add up; goal names are sanitized and redacted; only a
verified document is stored, and the agent then reads what the newest ones say together.

Linking (in development: the provider refuses third-party reads, see ADR-044) is a user-only HTTP flow, never an
agent tool: it handles a password and an access token, and an agent attempt is T3 CREDENTIAL_CHANGE (S31). The
password reaches the provider adapter and nothing else; the token is stored sealed and never leaves this layer.

The agent reads (get_investments, T0) the figures as the documents print them or the provider reported them, with
totals, contributions and gains computed in integers, and goal names wrapped as untrusted text (S30). Nothing here
moves money or recommends an instrument.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import Enum

from ...domain.agent.untrusted import sanitize, wrap_untrusted
from ...domain.audit.events import Actor, AuditDraft, AuditKind
from ...domain.investments.documents import (
    ISSUE_MESSAGES,
    MAX_GOAL_NAME,
    OLD_AFTER,
    DocumentIssue,
    InvestmentDocumentKind,
    MovementHistory,
    StoredInvestmentDocument,
    check_document,
    document_day,
    document_id,
    fund_id,
    goal_id,
    portfolio,
    portfolio_caveats,
    portfolio_facts,
)
from ...domain.investments.model import (
    INVESTMENTS_VERSION,
    InvestmentLink,
    InvestmentSnapshot,
    mask_email,
    overview_caveats,
    overview_facts,
    snapshot_from_report,
)
from ...domain.shared.envelope import Caveat, Envelope
from ...domain.shared.errors import InvalidInput
from ...domain.shared.hashing import content_id
from ...domain.user.account import normalize_email
from ..ports import (
    AuditLog,
    Clock,
    IdGenerator,
    InvestmentAccessRejected,
    InvestmentDocumentReader,
    InvestmentProvider,
    InvestmentProviderUnavailable,
    InvestmentStore,
    StatementReaderUnavailable,
    StatementUnreadable,
)
from ..services.redaction import StatementRedactor

CONSENT_VERSION = "inv-consent-1"  # the text the user accepted before linking, recorded on INVESTMENTS_LINKED
PASSWORD_MAX = 256
CURRENCY = "CLP"  # the provider reports goal values in pesos


class LinkStatus(str, Enum):
    LINKED = "LINKED"
    SYNCED = "SYNCED"
    UNLINKED = "UNLINKED"
    NOT_LINKED = "NOT_LINKED"
    INVALID_INPUT = "INVALID_INPUT"
    ACCESS_REJECTED = "ACCESS_REJECTED"  # the provider refused the email and password
    READ_REFUSED = "READ_REFUSED"  # the provider accepted the sign-in but refused to share the goals with that token
    RELINK_REQUIRED = "RELINK_REQUIRED"  # the provider no longer accepts the stored access, or another adapter issued it
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    CONFLICT = "CONFLICT"  # the link changed while the request ran; nothing was written


@dataclass(frozen=True, slots=True)
class LinkView:
    """What leaves the system about a link: never the token, and the email only masked."""

    provider: str
    email: str
    linked_at: str
    synced_at: str | None
    goals: int | None
    synthetic: bool
    relink_required: bool


@dataclass(frozen=True, slots=True)
class LinkOutcome:
    status: LinkStatus
    link: LinkView | None = None
    field: str | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class GoalView:
    goal_id: str
    name: dict[str, str]  # {"untrusted_text": ...}: the user's label at the provider
    value: int | None  # None when the imported documents do not describe the same shares
    deposited: int | None
    gain: int | None


@dataclass(frozen=True, slots=True)
class FundView:
    fund_id: str
    fund: str  # the provider's fund name ("Risky Norris"), a checked pattern, not free text
    series: str
    shares: str  # exact decimal text
    share_value: str  # pesos per share, exact decimal text
    value: int


@dataclass(frozen=True, slots=True)
class ContributionsView:
    """The contribution habits the transactions certificate shows: money from and to the bank only."""

    first_day: str
    last_day: str
    contributions: int
    withdrawals: int
    contributed: int
    withdrawn: int
    net_contributed: int
    months: int
    active_months: int
    monthly_average: int
    last_contribution: str | None
    complete: bool  # it starts when the account opened, so the gain can be computed


@dataclass(frozen=True, slots=True)
class DocumentView:
    """An imported document, without its rows."""

    document_id: str
    provider: str
    kind: str  # holdings | movements
    as_of: str | None  # None when the document's day could not be read
    imported_at: str | None  # None for a document that was not kept
    rows: int
    verified: bool
    issues: tuple[dict[str, str], ...]  # {"code", "message"}


@dataclass(frozen=True, slots=True)
class InvestmentOverview:
    provider: str
    currency: str
    source: str  # statement (imported documents) | sync (a linked account)
    as_of: str  # the day the values describe
    synced_at: str | None  # the sync's time, for a linked account
    synthetic: bool
    stale: bool  # a sync over 24 hours old, or a statement over a month old
    total_value: int | None  # None when only the transactions certificate was imported
    total_deposited: int | None  # net contributions; None when unknown
    total_gain: int | None
    gain_pct: float | None
    goals: tuple[GoalView, ...]
    funds: tuple[FundView, ...]
    contributions: ContributionsView | None
    documents: tuple[DocumentView, ...]  # the documents these figures come from
    documents_agree: bool | None  # the statement and the certificate describe the same shares; None unless both


@dataclass(frozen=True, slots=True)
class InvestmentDocumentImport:
    document: DocumentView
    duplicate: bool
    overview: InvestmentOverview | None  # what the agent reads from now on; None while nothing is imported


class InvestmentUseCases:
    def __init__(
        self,
        provider: InvestmentProvider,
        store: InvestmentStore,
        clock: Clock,
        ids: IdGenerator,
        *,
        reader: InvestmentDocumentReader | None = None,
        redactor: StatementRedactor | None = None,
        audit: AuditLog | None = None,
    ) -> None:
        self._provider = provider
        self._store = store
        self._clock = clock
        self._ids = ids
        self._reader = reader
        self._redactor = redactor
        self._audit = audit

    @property
    def adapter(self) -> str:
        return self._provider.name

    @property
    def provider(self) -> str:
        return self._provider.provider

    # ---- user-only flows (HTTP) ----------------------------------------------------------------

    def link(self, user_id: str, session_id: str, email: object, password: object, *, consent: bool) -> LinkOutcome:
        """Sign in to the provider once, read every goal and store the link. The password is used here and dropped."""
        if consent is not True:
            return LinkOutcome(LinkStatus.INVALID_INPUT, field="consent", message="the user must accept the consent text first")
        try:
            address = normalize_email(email if isinstance(email, str) else "")
        except InvalidInput as error:
            return LinkOutcome(LinkStatus.INVALID_INPUT, field=error.field, message=error.message)
        if not isinstance(password, str) or not 1 <= len(password) <= PASSWORD_MAX:
            return LinkOutcome(LinkStatus.INVALID_INPUT, field="password", message=f"use 1-{PASSWORD_MAX} characters")
        current = self._store.link(user_id)
        try:
            token = self._provider.authenticate(address, password)
        except InvestmentAccessRejected:
            return LinkOutcome(LinkStatus.ACCESS_REJECTED, message="the provider did not accept these credentials")
        except InvestmentProviderUnavailable:
            return LinkOutcome(LinkStatus.PROVIDER_UNAVAILABLE, message="the provider could not be reached; try again later")
        # The sign-in worked, so the credentials are right: whatever goes wrong next is never "wrong password".
        try:
            snapshot = self._read(user_id, address, token)
        except InvestmentAccessRejected:
            # Seen live with Fintual on 2026-10-19: a token from the sign-in, refused by /goals in every known style.
            return LinkOutcome(LinkStatus.READ_REFUSED, message="the provider accepted the sign-in but refused to share the goals")
        except InvestmentProviderUnavailable:
            return LinkOutcome(LinkStatus.PROVIDER_UNAVAILABLE, message="the provider accepted the sign-in but did not return the goals; try again later")
        link = InvestmentLink(user_id, self._provider.provider, self._provider.name, address, token, snapshot.fetched_at)
        detail = (
            f"provider={link.provider};adapter={link.adapter};goals={len(snapshot.goals)};consent={CONSENT_VERSION};"
            f"synthetic={'yes' if snapshot.synthetic else 'no'};relink={'yes' if current else 'no'}"
        )
        if not self._store.save(current, link, snapshot, (self._event(user_id, session_id, AuditKind.INVESTMENTS_LINKED, detail),)):
            return LinkOutcome(LinkStatus.CONFLICT, message="the link changed meanwhile; reload and retry")
        return LinkOutcome(LinkStatus.LINKED, _view(link, snapshot))

    def sync(self, user_id: str, session_id: str) -> LinkOutcome:
        """Read every goal again with the stored token. A refused token marks the link for relinking."""
        link = self._store.link(user_id)
        if link is None:
            return LinkOutcome(LinkStatus.NOT_LINKED, message="no investment account is linked")
        latest = self._store.latest(user_id)
        if link.expired or link.adapter != self._provider.name:
            return LinkOutcome(LinkStatus.RELINK_REQUIRED, _view(link, latest), message="link the account again")
        try:
            snapshot = self._read(user_id, link.email, link.token)
        except InvestmentAccessRejected:
            expired = replace(link, expired=True)
            self._store.save(link, expired, None, ())  # a concurrent change wins; either way the user relinks
            return LinkOutcome(LinkStatus.RELINK_REQUIRED, _view(expired, latest), message="the provider no longer accepts this link; link it again")
        except InvestmentProviderUnavailable:
            return LinkOutcome(LinkStatus.PROVIDER_UNAVAILABLE, _view(link, latest), message="the provider could not be reached; try again later")
        detail = f"provider={link.provider};adapter={link.adapter};goals={len(snapshot.goals)}"
        if not self._store.save(link, link, snapshot, (self._event(user_id, session_id, AuditKind.INVESTMENTS_SYNCED, detail),)):
            return LinkOutcome(LinkStatus.CONFLICT, message="the link changed meanwhile; reload and retry")
        return LinkOutcome(LinkStatus.SYNCED, _view(link, snapshot))

    def unlink(self, user_id: str, session_id: str) -> LinkOutcome:
        """Delete the token and every synced snapshot. The provider keeps the account; only our copy goes."""
        link = self._store.link(user_id)
        if link is None:
            return LinkOutcome(LinkStatus.NOT_LINKED, message="no investment account is linked")
        event = self._event(user_id, session_id, AuditKind.INVESTMENTS_UNLINKED, f"provider={link.provider};adapter={link.adapter}")
        if self._store.remove(user_id, (event,)) == 0:
            return LinkOutcome(LinkStatus.NOT_LINKED, message="no investment account is linked")
        return LinkOutcome(LinkStatus.UNLINKED)

    def status(self, user_id: str) -> LinkOutcome:
        link = self._store.link(user_id)
        if link is None:
            return LinkOutcome(LinkStatus.NOT_LINKED, message="no investment account is linked")
        return LinkOutcome(LinkStatus.LINKED, _view(link, self._store.latest(user_id)))

    # ---- statements the user imports (HTTP, or a file dropped on the copilot) ----------------------

    def import_document(self, user_id: str, session_id: str, content: bytes) -> Envelope[InvestmentDocumentImport]:
        """Read a document the provider issued, check that it adds up and keep it for the agent, verified only.

        The file is the user's own download and never reaches a model. A document that does not add up is reported
        with its issues and nothing from it is kept. Importing the same document again changes nothing."""
        if self._reader is None or self._redactor is None or self._audit is None:
            return Envelope.insufficient(("document_reader",), params_version=INVESTMENTS_VERSION, message="investment statements cannot be read here")
        try:
            read = self._reader.read(content)
        except StatementUnreadable as exc:
            return Envelope.invalid("file", ("investment_statement",), params_version=INVESTMENTS_VERSION, message=str(exc))
        except StatementReaderUnavailable as exc:
            return Envelope.insufficient(("document_reader",), params_version=INVESTMENTS_VERSION, message=str(exc))
        now = self._clock.now()
        issues = check_document(read, now.date())
        day = document_day(read)
        doc_id = document_id(user_id, read)
        detail = (
            f"provider={read.provider};kind={read.kind.value};rows={len(read.positions) + len(read.movements)};"
            f"issues={','.join(i.value for i in issues) or 'none'};reader={self._reader.name}"
        )
        duplicate, kept = False, None
        if issues or day is None:
            self._record(user_id, session_id, "UNVERIFIED", detail, doc_id)
        else:
            redactor = self._redactor
            kept = StoredInvestmentDocument(
                doc_id, user_id, read.provider, read.kind, now, day, read.positions, read.total,
                tuple(replace(m, goal=_goal_name(redactor, m.goal)) for m in read.movements),
            )
            event = self._draft(user_id, session_id, AuditKind.INVESTMENT_DOCUMENT_IMPORTED, detail, "VERIFIED", doc_id)
            if not self._store.add_document(kept, (event,)):
                duplicate = True
                self._record(user_id, session_id, "DUPLICATE", detail, doc_id)
        view = DocumentView(
            doc_id, read.provider, read.kind.value, day.isoformat() if day else None, now.isoformat() if kept else None,
            len(read.positions) + len(read.movements), kept is not None, _issues(issues),
        )
        overview = self.overview(user_id)
        caveats = list(_import_caveats(read.kind, issues, duplicate))
        if overview.ok:
            caveats += [w for w in overview.warnings if w not in caveats]
        return Envelope.success(
            InvestmentDocumentImport(view, duplicate, overview.data if overview.ok else None),
            params_version=INVESTMENTS_VERSION,
            snapshot_id=doc_id,
            as_of=now.isoformat(),
            facts=overview.facts if overview.ok else (),
            warnings=tuple(caveats),
        )

    def remove_documents(self, user_id: str, session_id: str) -> int:
        """Delete every imported document of the user. Returns how many; the audit keeps the count, nothing else."""
        count = len(self._store.documents(user_id))
        if not count:
            return 0
        event = self._draft(user_id, session_id, AuditKind.INVESTMENT_DOCUMENTS_REMOVED, f"documents={count}", "REMOVED", None)
        return self._store.remove_documents(user_id, (event,))

    # ---- the agent's read (T0) and GET /v1/investments -----------------------------------------

    def overview(self, user_id: str) -> Envelope[InvestmentOverview]:
        """The newest imported documents, else the last synced snapshot. No network: importing and syncing are the
        user's actions, so the figures carry their day."""
        documents = self._store.documents(user_id)
        if documents:
            return self._from_documents(user_id, documents)
        snapshot = self._store.latest(user_id)
        if snapshot is None:
            return Envelope.insufficient(
                ("investment_account",),
                params_version=INVESTMENTS_VERSION,
                message="no investment statement is imported; the user drops the provider's statement in the app's Investments section",
            )
        now = self._clock.now()
        data = InvestmentOverview(
            provider=snapshot.provider,
            currency=snapshot.currency,
            source="sync",
            as_of=snapshot.fetched_at.date().isoformat(),
            synced_at=snapshot.fetched_at.isoformat(),
            synthetic=snapshot.synthetic,
            stale=snapshot.is_stale(now),
            total_value=snapshot.total_value,
            total_deposited=snapshot.total_deposited,
            total_gain=snapshot.total_gain,
            gain_pct=None,
            goals=tuple(GoalView(g.goal_id, wrap_untrusted(g.name), g.value, g.deposited, g.gain) for g in snapshot.goals),
            funds=(),
            contributions=None,
            documents=(),
            documents_agree=None,
        )
        return Envelope.success(
            data, params_version=INVESTMENTS_VERSION, snapshot_id=snapshot.snapshot_id, as_of=snapshot.fetched_at.isoformat(),
            facts=overview_facts(snapshot), warnings=overview_caveats(snapshot, now),
        )

    def _from_documents(self, user_id: str, documents: Sequence[StoredInvestmentDocument]) -> Envelope[InvestmentOverview]:
        holdings = _newest(documents, InvestmentDocumentKind.HOLDINGS)
        movements = _newest(documents, InvestmentDocumentKind.MOVEMENTS)
        used = tuple(d for d in (holdings, movements) if d is not None)
        provider = used[0].provider
        p = portfolio(provider, holdings, movements)
        today = self._clock.now().date()
        data = InvestmentOverview(
            provider=provider,
            currency="CLP",
            source="statement",
            as_of=p.as_of.isoformat(),
            synced_at=None,
            synthetic=False,
            stale=today - p.as_of > OLD_AFTER,
            total_value=p.total_value,
            total_deposited=p.total_deposited,
            total_gain=p.total_gain,
            gain_pct=float(p.gain_pct) if p.gain_pct is not None else None,
            goals=tuple(GoalView(goal_id(provider, g.goal), wrap_untrusted(g.goal), g.value, g.net_contributed, g.gain) for g in p.goals),
            funds=tuple(FundView(fund_id(f), f.fund, f.series, str(f.shares), str(f.share_value), f.balance) for f in p.positions),
            contributions=_contributions(p.history),
            documents=tuple(_document_view(d) for d in used),
            documents_agree=p.agree,
        )
        return Envelope.success(
            data,
            params_version=INVESTMENTS_VERSION,
            snapshot_id=content_id("invp", user_id, *(d.document_id for d in used)),
            as_of=p.as_of.isoformat(),
            facts=portfolio_facts(p),
            warnings=portfolio_caveats(p, today),
        )

    # ---- helpers -------------------------------------------------------------------------------

    def _read(self, user_id: str, email: str, token: str) -> InvestmentSnapshot:
        reported = self._provider.goals(email, token)
        try:
            return snapshot_from_report(user_id, self._provider.provider, CURRENCY, self._clock.now(), reported, synthetic=self._provider.synthetic)
        except InvalidInput as error:  # the provider answered outside its own contract: store nothing
            raise InvestmentProviderUnavailable(f"the provider returned an unexpected {error.field}") from None

    def _event(self, user_id: str, session_id: str, kind: AuditKind, detail: str) -> AuditDraft:
        return AuditDraft(
            event_id=self._ids.new("evt"), timestamp=self._clock.now(), session_id=session_id,
            user_id=user_id, actor=Actor.USER, kind=kind, detail=detail,
        )

    def _draft(self, user_id: str, session_id: str, kind: AuditKind, detail: str, result: str, snapshot: str | None) -> AuditDraft:
        event = self._event(user_id, session_id, kind, detail)
        return replace(event, execution_result=result, forecast_snapshot_id=snapshot, policy_version=INVESTMENTS_VERSION)

    def _record(self, user_id: str, session_id: str, result: str, detail: str, snapshot: str) -> None:
        """An import that stores nothing (unverified, or already there) is audited on its own."""
        if self._audit is not None:
            self._audit.append(self._draft(user_id, session_id, AuditKind.INVESTMENT_DOCUMENT_IMPORTED, detail, result, snapshot))


def _goal_name(redactor: StatementRedactor, name: str) -> str:
    """The user's label as it may be stored and shown: control characters out, personal data masked (ADR-028)."""
    return redactor.redact_text(sanitize(name))[0][:MAX_GOAL_NAME]


def _newest(documents: Sequence[StoredInvestmentDocument], kind: InvestmentDocumentKind) -> StoredInvestmentDocument | None:
    """The newest document of a kind by its day; of two for the same day, the later import."""
    found = [(d.as_of, i, d) for i, d in enumerate(documents) if d.kind is kind]
    return max(found, key=lambda item: (item[0], item[1]))[2] if found else None


def _issues(issues: Sequence[DocumentIssue]) -> tuple[dict[str, str], ...]:
    return tuple({"code": issue.value, "message": ISSUE_MESSAGES[issue]} for issue in issues)


def _document_view(d: StoredInvestmentDocument) -> DocumentView:
    return DocumentView(d.document_id, d.provider, d.kind.value, d.as_of.isoformat(), d.imported_at.isoformat(), d.rows, True, ())


def _contributions(h: MovementHistory | None) -> ContributionsView | None:
    if h is None:
        return None
    return ContributionsView(
        first_day=h.first_day.isoformat(),
        last_day=h.last_day.isoformat(),
        contributions=h.contributions,
        withdrawals=h.withdrawals,
        contributed=h.contributed,
        withdrawn=h.withdrawn,
        net_contributed=h.net_contributed,
        months=h.months,
        active_months=h.active_months,
        monthly_average=h.monthly_average,
        last_contribution=h.last_contribution.isoformat() if h.last_contribution else None,
        complete=h.complete,
    )


def _import_caveats(kind: InvestmentDocumentKind, issues: Sequence[DocumentIssue], duplicate: bool) -> tuple[Caveat, ...]:
    what = "investment statement" if kind is InvestmentDocumentKind.HOLDINGS else "transactions certificate"
    if issues:
        codes = ", ".join(i.value for i in issues)
        unverified = (
            "could not be verified", "couldn't be verified", "not verified", "no se pudo verificar", "no pude verificar", "no se verificó",
        )
        message = f"The {what} could not be verified ({codes}); nothing from it was kept. A fresh download from the provider usually reads well."
        return (Caveat("INVESTMENT_DOCUMENT_UNVERIFIED", message, unverified),)
    if duplicate:
        already = ("already imported", "ya estaba", "ya se había", "ya lo había")
        return (Caveat("INVESTMENT_DOCUMENT_DUPLICATE", f"This {what} was already imported; nothing changed.", already),)
    return ()


def _view(link: InvestmentLink, snapshot: InvestmentSnapshot | None) -> LinkView:
    return LinkView(
        provider=link.provider,
        email=mask_email(link.email),
        linked_at=link.linked_at.isoformat(),
        synced_at=snapshot.fetched_at.isoformat() if snapshot else None,
        goals=len(snapshot.goals) if snapshot else None,
        synthetic=snapshot.synthetic if snapshot else False,
        relink_required=link.expired,
    )
