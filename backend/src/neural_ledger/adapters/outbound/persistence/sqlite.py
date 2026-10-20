"""SQLite adapters (standard library sqlite3): durable actions and audit log, zero services.

Same ports as the in-memory adapters; tests/adapters run one contract suite against both.
Postgres would be one more adapter behind the same ports.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from ....application.ports import ErasureReport, IdCollision, ImportCommit, MemoryWriteResult
from ....domain.actions.terms import (
    ActionTerms,
    ActionType,
    Authorization,
    Frequency,
    Proposal,
    ProposalStatus,
    SavingsRule,
)
from ....domain.audit.events import ERASED_SESSION, ERASURE_KINDS, GENESIS_HASH, AuditDraft, AuditEvent, erasure_detail, seal, tombstone
from ....domain.connections.model import Connection, ConnectionKind, ConnectionSnapshot, RemoteTool
from ....domain.finance.profile import RiskProfile
from ....domain.investments.documents import (
    MAX_DOCUMENTS,
    FundMovement,
    FundPosition,
    InvestmentDocumentKind,
    StoredInvestmentDocument,
)
from ....domain.investments.model import MAX_SNAPSHOTS, InvestmentGoal, InvestmentLink, InvestmentSnapshot
from ....domain.ledger.categorization import PostedTransaction
from ....domain.ledger.entities import AccountType, InstallmentInfo, Transaction, TransactionKind
from ....domain.memory.catalog import Declaration, MemoryType, check_appended, declaration_record, parse_declaration
from ....domain.memory.consent import Consent, MemoryState, parse_state, state_record, with_consent, with_memory_change
from ....domain.memory.proposals import (
    MemoryProposal,
    ProposalState,
    WriteOutcome,
    check_confirmation,
    confirmation_event,
    consent_detail,
    decide_confirmation,
    decide_preparation,
    deletion_detail,
    parse_proposal,
    proposal_record,
)
from ....domain.memory.transitions import check_import_batch
from ....domain.receipts.model import ReceiptIssue, ReceiptIssueCode, StoredReceipt
from ....domain.shared.month import Month
from ....domain.shared.serialization import to_primitive
from ....domain.statements.model import (
    BankStatement,
    CardObligations,
    DailyBalance,
    Installment,
    Issue,
    IssueCode,
    LineKind,
    ScheduledAmount,
    SectionTotal,
    StatementLine,
    StatementSummary,
    StoredStatement,
)
from ....domain.user.account import Session, UserAccount
from ....domain.user.profile import QuestionnaireAnswer, UserProfile
from .field_cipher import FieldCipher, FieldCipherError, WrongDataKey

# Schema version 1 (PRAGMA user_version): every personal payload sealed (field_cipher.py), proposals, authorizations
# and audit events carry their owner, and accounts are found by the email's blind index. A database from before has
# user_version 0 and is upgraded by sqlite_migration.migrate, which bootstrap runs before any store is used.
# A table or index added later without touching existing rows (user_memory, ADR-048) keeps the version: every
# CREATE is IF NOT EXISTS and runs each time a current file is opened, so an existing database gains it empty.
# That is additive initialization, not a downgrade guarantee: an older binary still opens such a file but does not
# know user_memory, so its erasure and reset would leave memory behind. Never run an older binary on a database
# that holds memory (docs/SECURITY.md, "No downgrade").
SCHEMA_VERSION = 1
_SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
    proposal_id TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    payload     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS authorizations (
    authorization_id TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL,
    session_id       TEXT NOT NULL,
    payload          TEXT NOT NULL,
    consumed_at      TEXT
);
CREATE TABLE IF NOT EXISTS audit_events (
    sequence   INTEGER PRIMARY KEY,
    event_id   TEXT NOT NULL UNIQUE,
    user_id    TEXT,
    session_id TEXT NOT NULL,
    record     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS statements (
    sequence     INTEGER PRIMARY KEY,
    statement_id TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    payload      TEXT NOT NULL,
    UNIQUE (user_id, statement_id)
);
CREATE TABLE IF NOT EXISTS transactions (
    sequence  INTEGER PRIMARY KEY,
    txn_id    TEXT NOT NULL,
    user_id   TEXT NOT NULL,
    posted_on TEXT NOT NULL,
    payload   TEXT NOT NULL,
    UNIQUE (user_id, txn_id)
);
CREATE TABLE IF NOT EXISTS receipts (
    sequence   INTEGER PRIMARY KEY,
    receipt_id TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    payload    TEXT NOT NULL,
    UNIQUE (user_id, receipt_id)
);
CREATE TABLE IF NOT EXISTS connections (
    sequence      INTEGER PRIMARY KEY,
    connection_id TEXT NOT NULL,
    user_id       TEXT NOT NULL,
    payload       TEXT NOT NULL,
    UNIQUE (user_id, connection_id)
);
CREATE TABLE IF NOT EXISTS connection_results (
    sequence      INTEGER PRIMARY KEY,
    connection_id TEXT NOT NULL,
    user_id       TEXT NOT NULL,
    tool          TEXT NOT NULL,
    payload       TEXT NOT NULL,
    UNIQUE (user_id, connection_id, tool)
);
CREATE TABLE IF NOT EXISTS savings_rules (
    sequence INTEGER PRIMARY KEY,
    rule_id  TEXT NOT NULL UNIQUE,
    user_id  TEXT NOT NULL,
    payload  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_accounts (
    user_id     TEXT PRIMARY KEY,
    email_index TEXT NOT NULL UNIQUE,
    payload     TEXT NOT NULL,
    sample_data INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
    session_ref TEXT PRIMARY KEY,
    token_hash  TEXT NOT NULL UNIQUE,
    user_id     TEXT NOT NULL,
    payload     TEXT NOT NULL,
    revoked_at  TEXT
);
CREATE TABLE IF NOT EXISTS user_memory (
    sequence  INTEGER PRIMARY KEY,
    memory_id TEXT NOT NULL UNIQUE,
    chain_id  TEXT NOT NULL,
    version   INTEGER NOT NULL,
    user_id   TEXT NOT NULL,
    type      TEXT NOT NULL,
    payload   TEXT NOT NULL,
    UNIQUE (chain_id, version)
);
CREATE UNIQUE INDEX IF NOT EXISTS user_memory_one_chain ON user_memory (user_id, type) WHERE version = 1;
CREATE TABLE IF NOT EXISTS memory_state (
    user_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory_proposals (
    proposal_id TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS memory_proposals_by_user ON memory_proposals (user_id);
CREATE TABLE IF NOT EXISTS meta (
    name  TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS investment_links (
    user_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS investment_snapshots (
    sequence    INTEGER PRIMARY KEY,
    snapshot_id TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS investment_snapshots_by_user ON investment_snapshots (user_id, sequence);
CREATE TABLE IF NOT EXISTS investment_documents (
    sequence    INTEGER PRIMARY KEY,
    document_id TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    payload     TEXT NOT NULL,
    UNIQUE (user_id, document_id)
);
"""
_SCHEMA_STATEMENTS = tuple(statement.strip() for statement in _SCHEMA.split(";") if statement.strip())


# Literal statements per table (no SQL built from strings, ASVS V1). Whoever adds a table to _SCHEMA must add it here too.
_RESET_SQL: dict[str, tuple[str, str]] = {
    "proposals": ("SELECT COUNT(*) FROM proposals", "DELETE FROM proposals"),
    "authorizations": ("SELECT COUNT(*) FROM authorizations", "DELETE FROM authorizations"),
    "audit_events": ("SELECT COUNT(*) FROM audit_events", "DELETE FROM audit_events"),
    "statements": ("SELECT COUNT(*) FROM statements", "DELETE FROM statements"),
    "transactions": ("SELECT COUNT(*) FROM transactions", "DELETE FROM transactions"),
    "receipts": ("SELECT COUNT(*) FROM receipts", "DELETE FROM receipts"),
    "connections": ("SELECT COUNT(*) FROM connections", "DELETE FROM connections"),
    "connection_results": ("SELECT COUNT(*) FROM connection_results", "DELETE FROM connection_results"),
    "savings_rules": ("SELECT COUNT(*) FROM savings_rules", "DELETE FROM savings_rules"),
    "user_profiles": ("SELECT COUNT(*) FROM user_profiles", "DELETE FROM user_profiles"),
    "user_accounts": ("SELECT COUNT(*) FROM user_accounts", "DELETE FROM user_accounts"),
    "sessions": ("SELECT COUNT(*) FROM sessions", "DELETE FROM sessions"),
    "investment_links": ("SELECT COUNT(*) FROM investment_links", "DELETE FROM investment_links"),
    "investment_snapshots": ("SELECT COUNT(*) FROM investment_snapshots", "DELETE FROM investment_snapshots"),
    "investment_documents": ("SELECT COUNT(*) FROM investment_documents", "DELETE FROM investment_documents"),
    "user_memory": ("SELECT COUNT(*) FROM user_memory", "DELETE FROM user_memory"),
    "memory_state": ("SELECT COUNT(*) FROM memory_state", "DELETE FROM memory_state"),
    "memory_proposals": ("SELECT COUNT(*) FROM memory_proposals", "DELETE FROM memory_proposals"),
}
# Bookkeeping, not data: a reset keeps it (the key check stays valid, since a reset does not change the key).
_KEPT_ON_RESET = frozenset({"meta"})


class SqliteDatabase:
    def __init__(self, path: str | Path) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA secure_delete=ON")  # deleted rows are overwritten, not left in free pages
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if version < SCHEMA_VERSION and self._tables():
            self.schema_version = version  # an older file: migrate() upgrades it, with the data key, before any store runs
        else:
            create_schema(self.connection)
            self.schema_version = SCHEMA_VERSION
        # One connection is shared by every request thread, so every use of it, reads included,
        # goes through this lock. Unserialized reads interleave cursors across threads.
        self.lock = threading.Lock()

    @property
    def needs_migration(self) -> bool:
        return self.schema_version < SCHEMA_VERSION

    def fetchone(self, sql: str, params: tuple = ()) -> tuple | None:
        with self.lock:
            return self.connection.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self.lock:
            return self.connection.execute(sql, params).fetchall()

    def _tables(self) -> list[str]:
        rows = self.connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\' ORDER BY name").fetchall()
        return [name for (name,) in rows]

    def _known_tables(self) -> list[str]:
        """The tables to empty; refuses a table that _RESET_SQL does not know, so none is ever skipped silently."""
        present = [name for name in self._tables() if name not in _KEPT_ON_RESET]
        unknown = [name for name in present if name not in _RESET_SQL]
        if unknown:
            raise RuntimeError(f"no reset statements for table(s) {', '.join(unknown)}: add them to _RESET_SQL")
        return present

    def counts(self) -> dict[str, int]:
        """Rows per table (read-only)."""
        with self.lock:
            return {t: self.connection.execute(_RESET_SQL[t][0]).fetchone()[0] for t in self._known_tables()}

    def reset(self) -> dict[str, int]:
        """Delete every row of every table in one transaction and return the rows deleted per table.

        The file and the schema stay, so a process holding the same database keeps working (the audit chain restarts from genesis).
        """
        with self.lock:
            tables = self._known_tables()
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                deleted: dict[str, int] = {}
                for table in tables:
                    count_sql, delete_sql = _RESET_SQL[table]
                    deleted[table] = self.connection.execute(count_sql).fetchone()[0]
                    self.connection.execute(delete_sql)
                self.connection.execute("COMMIT")
            except BaseException:
                self.connection.execute("ROLLBACK")
                raise
            return deleted


def create_schema(conn: sqlite3.Connection) -> None:
    """Every table that is missing, at the current version. Statement by statement: executescript would COMMIT
    a transaction the caller holds (the migration runs this inside one)."""
    for statement in _SCHEMA_STATEMENTS:
        conn.execute(statement)
    conn.execute("PRAGMA user_version = 1")  # SCHEMA_VERSION; a PRAGMA takes no parameters


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {name for (name,) in conn.execute("SELECT name FROM pragma_table_info(?)", (table,))}


def upgrade_schema(conn: sqlite3.Connection, cipher: FieldCipher) -> int:
    """Schema 0 -> 1, inside the caller's transaction; returns the version it found. Rows are copied as they are:
    the migration seals what is still in clear right after (SEALED_COLUMNS).

    Version 0 kept the email in clear as the account lookup, and proposals, authorizations and audit events
    without their owner in a column (their payloads, plain JSON then, carry it). Those four tables are rebuilt:
    accounts get the email's blind index, the others their user_id."""
    found = conn.execute("PRAGMA user_version").fetchone()[0]
    if found >= SCHEMA_VERSION:
        return found
    present = {name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    rebuilt: list[str] = []
    if "user_accounts" in present and "email_index" not in _columns(conn, "user_accounts"):
        conn.execute("ALTER TABLE user_accounts RENAME TO user_accounts_v0")
        rebuilt.append("user_accounts")
    if "proposals" in present and "user_id" not in _columns(conn, "proposals"):
        conn.execute("ALTER TABLE proposals RENAME TO proposals_v0")
        rebuilt.append("proposals")
    if "authorizations" in present and "user_id" not in _columns(conn, "authorizations"):
        conn.execute("ALTER TABLE authorizations RENAME TO authorizations_v0")
        rebuilt.append("authorizations")
    if "audit_events" in present and "user_id" not in _columns(conn, "audit_events"):
        conn.execute("ALTER TABLE audit_events RENAME TO audit_events_v0")
        rebuilt.append("audit_events")
    create_schema(conn)
    if "user_accounts" in rebuilt:
        for user_id, email, payload, sample_data in conn.execute("SELECT user_id, email, payload, sample_data FROM user_accounts_v0").fetchall():
            conn.execute(
                "INSERT INTO user_accounts (user_id, email_index, payload, sample_data) VALUES (?, ?, ?, ?)",
                (user_id, email_index(cipher, email), payload, sample_data),
            )
        conn.execute("DROP TABLE user_accounts_v0")
    if "proposals" in rebuilt:
        for proposal_id, session_id, payload in conn.execute("SELECT proposal_id, session_id, payload FROM proposals_v0").fetchall():
            conn.execute(
                "INSERT INTO proposals (proposal_id, user_id, session_id, payload) VALUES (?, ?, ?, ?)",
                (proposal_id, json.loads(payload)["user_id"], session_id, payload),
            )
        conn.execute("DROP TABLE proposals_v0")
    if "authorizations" in rebuilt:
        rows = conn.execute("SELECT authorization_id, session_id, payload, consumed_at FROM authorizations_v0").fetchall()
        for authorization_id, session_id, payload, consumed_at in rows:
            conn.execute(
                "INSERT INTO authorizations (authorization_id, user_id, session_id, payload, consumed_at) VALUES (?, ?, ?, ?, ?)",
                (authorization_id, json.loads(payload)["user_id"], session_id, payload, consumed_at),
            )
        conn.execute("DROP TABLE authorizations_v0")
    if "audit_events" in rebuilt:
        rows = conn.execute("SELECT sequence, event_id, session_id, record FROM audit_events_v0 ORDER BY sequence").fetchall()
        for sequence, event_id, session_id, record in rows:
            conn.execute(
                "INSERT INTO audit_events (sequence, event_id, user_id, session_id, record) VALUES (?, ?, ?, ?, ?)",
                (sequence, event_id, json.loads(record).get("user_id"), session_id, record),
            )
        conn.execute("DROP TABLE audit_events_v0")
    return found


def _aad(table: str, user_id: str | None, row_id: str) -> str:
    """Associated data that binds a sealed value to its table, owner and row."""
    return f"{table}|{user_id or ''}|{row_id}"


def _profile_from(payload: dict) -> UserProfile:
    return UserProfile(
        user_id=payload["user_id"],
        display_name=payload["display_name"],
        language=payload["language"],
        declared_tolerance=RiskProfile(payload["declared_tolerance"]) if payload["declared_tolerance"] is not None else None,
        questionnaire=tuple(QuestionnaireAnswer(**answer) for answer in payload["questionnaire"]),
        questionnaire_version=payload["questionnaire_version"],
    )


def _seal_profile(cipher: FieldCipher, profile: UserProfile) -> str:
    return cipher.seal(json.dumps(to_primitive(profile)), _aad("user_profiles", profile.user_id, profile.user_id))


def _open_profile(cipher: FieldCipher, user_id: str, payload: str) -> UserProfile:
    return _profile_from(json.loads(cipher.open(payload, _aad("user_profiles", user_id, user_id))))


class SqliteUserProfileStore:
    """Display name, language, declared tolerance and questionnaire answers, sealed with the data key."""

    def __init__(self, db: SqliteDatabase, cipher: FieldCipher) -> None:
        self._db = db
        self._cipher = cipher

    def get(self, user_id: str) -> UserProfile | None:
        row = self._db.fetchone("SELECT payload FROM user_profiles WHERE user_id = ?", (user_id,))
        return _open_profile(self._cipher, user_id, row[0]) if row else None

    def put(self, profile: UserProfile) -> None:
        with self._db.lock:
            self._db.connection.execute(
                "INSERT INTO user_profiles (user_id, payload) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET payload = excluded.payload",
                (profile.user_id, _seal_profile(self._cipher, profile)),
            )


def _account_from(payload: dict, sample_data: int) -> UserAccount:
    return UserAccount(
        user_id=payload["user_id"],
        email=payload["email"],
        password_hash=payload["password_hash"],
        created_at=datetime.fromisoformat(payload["created_at"]),
        sample_data=bool(sample_data),
    )


def email_index(cipher: FieldCipher, email: str) -> str:
    """The only searchable form of an email: HMAC-SHA256 of the normalized address under the derived index key."""
    return cipher.blind_index("email", email)


def _account_row(cipher: FieldCipher, account: UserAccount) -> tuple[str, str, str, int]:
    payload = to_primitive(account)
    payload.pop("sample_data", None)
    sealed = cipher.seal(json.dumps(payload), _aad("user_accounts", account.user_id, account.user_id))
    return account.user_id, email_index(cipher, account.email), sealed, int(account.sample_data)


def _open_account(cipher: FieldCipher, row: tuple) -> UserAccount:
    user_id, payload, sample_data = row
    return _account_from(json.loads(cipher.open(payload, _aad("user_accounts", user_id, user_id))), sample_data)


class SqliteUserAccountStore:
    """The email and the password hash are sealed; the email is found by its blind index, never stored in clear."""

    def __init__(self, db: SqliteDatabase, cipher: FieldCipher) -> None:
        self._db = db
        self._cipher = cipher

    def add(self, account: UserAccount) -> bool:
        with self._db.lock:
            cursor = self._db.connection.execute(
                "INSERT OR IGNORE INTO user_accounts (user_id, email_index, payload, sample_data) VALUES (?, ?, ?, ?)",
                _account_row(self._cipher, account),
            )
            return cursor.rowcount == 1

    def get(self, user_id: str) -> UserAccount | None:
        row = self._db.fetchone("SELECT user_id, payload, sample_data FROM user_accounts WHERE user_id = ?", (user_id,))
        return _open_account(self._cipher, row) if row else None

    def by_email(self, email: str) -> UserAccount | None:
        row = self._db.fetchone(
            "SELECT user_id, payload, sample_data FROM user_accounts WHERE email_index = ?", (email_index(self._cipher, email),)
        )
        account = _open_account(self._cipher, row) if row else None
        return account if account is not None and account.email == email else None

    def set_sample_data(self, user_id: str, enabled: bool) -> bool:
        with self._db.lock:
            cursor = self._db.connection.execute(
                "UPDATE user_accounts SET sample_data = ? WHERE user_id = ?", (int(enabled), user_id)
            )
            return cursor.rowcount == 1


def _session_from(payload: dict, revoked_at: str | None) -> Session:
    return Session(
        session_ref=payload["session_ref"],
        user_id=payload["user_id"],
        token_hash=payload["token_hash"],
        created_at=datetime.fromisoformat(payload["created_at"]),
        expires_at=datetime.fromisoformat(payload["expires_at"]),
        revoked_at=datetime.fromisoformat(revoked_at) if revoked_at else None,
    )


def _session_row(session: Session) -> tuple[str, str, str, str, str | None]:
    payload = to_primitive(session)
    payload.pop("revoked_at", None)
    revoked_at = session.revoked_at.isoformat() if session.revoked_at else None
    return session.session_ref, session.token_hash, session.user_id, json.dumps(payload), revoked_at


class SqliteSessionStore:
    """Rows are keyed by the token's sha256 digest; the token itself is never written."""

    def __init__(self, db: SqliteDatabase) -> None:
        self._db = db

    def add(self, session: Session) -> None:
        with self._db.lock:
            self._db.connection.execute(
                "INSERT INTO sessions (session_ref, token_hash, user_id, payload, revoked_at) VALUES (?, ?, ?, ?, ?)",
                _session_row(session),
            )

    def by_token_hash(self, token_hash: str) -> Session | None:
        row = self._db.fetchone("SELECT payload, revoked_at FROM sessions WHERE token_hash = ?", (token_hash,))
        return _session_from(json.loads(row[0]), row[1]) if row else None

    def revoke(self, session_ref: str, at: datetime) -> bool:
        with self._db.lock:
            cursor = self._db.connection.execute(
                "UPDATE sessions SET revoked_at = ? WHERE session_ref = ? AND revoked_at IS NULL", (at.isoformat(), session_ref)
            )
            return cursor.rowcount == 1


def _proposal_from(payload: dict) -> Proposal:
    return Proposal(
        proposal_id=payload["proposal_id"],
        session_id=payload["session_id"],
        user_id=payload["user_id"],
        terms=ActionTerms.from_primitive(payload["terms"]),
        source_snapshot_id=payload["source_snapshot_id"],
        created_at=datetime.fromisoformat(payload["created_at"]),
        expires_at=datetime.fromisoformat(payload["expires_at"]),
        status=ProposalStatus(payload["status"]),
    )


def _authorization_from(payload: dict, consumed_at: str | None) -> Authorization:
    return Authorization(
        authorization_id=payload["authorization_id"],
        proposal_id=payload["proposal_id"],
        session_id=payload["session_id"],
        user_id=payload["user_id"],
        terms=ActionTerms.from_primitive(payload["terms"]),
        action_hash=payload["action_hash"],
        created_at=datetime.fromisoformat(payload["created_at"]),
        expires_at=datetime.fromisoformat(payload["expires_at"]),
        consumed_at=datetime.fromisoformat(consumed_at) if consumed_at else None,
    )


def _rule_from(payload: dict) -> SavingsRule:
    return SavingsRule(
        rule_id=payload["rule_id"],
        user_id=payload["user_id"],
        amount=int(payload["amount"]),
        currency=payload["currency"],
        frequency=Frequency(payload["frequency"]),
        source_account=payload["source_account"],
        destination=payload["destination"],
        effective_date=date.fromisoformat(payload["effective_date"]),
        authorization_id=payload["authorization_id"],
        action=ActionType(payload.get("action", ActionType.CREATE_SAVINGS_RULE.value)),  # rules stored before ADR-037 are transfers
    )


def _date_or_none(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _decimal_or_none(value: float | None) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _installment_from(payload: dict | None) -> Installment | None:
    if not payload:
        return None
    return Installment(
        number=payload["number"],
        total=payload["total"],
        original_amount=payload.get("original_amount"),
        monthly_rate=_decimal_or_none(payload.get("monthly_rate")),
        purchased_on=_date_or_none(payload.get("purchased_on")),
    )


def _obligations_from(payload: dict | None) -> CardObligations | None:
    if not payload:
        return None
    return CardObligations(
        amount_due=payload.get("amount_due"),
        minimum_due=payload.get("minimum_due"),
        due_date=_date_or_none(payload.get("due_date")),
        credit_limit=payload.get("credit_limit"),
        credit_used=payload.get("credit_used"),
        credit_available=payload.get("credit_available"),
        upcoming=tuple(ScheduledAmount(Month.parse(u["month"]), int(u["amount"])) for u in payload.get("upcoming", ())),
    )


def _stored_statement_from(payload: dict) -> StoredStatement:
    st = payload["statement"]
    summary = st.get("summary")
    return StoredStatement(
        statement_id=payload["statement_id"],
        user_id=payload["user_id"],
        imported_at=datetime.fromisoformat(payload["imported_at"]),
        statement=BankStatement(
            bank=st["bank"],
            account_ref=st["account_ref"],
            currency=st["currency"],
            period_start=date.fromisoformat(st["period_start"]),
            period_end=date.fromisoformat(st["period_end"]),
            lines=tuple(
                StatementLine(
                    index=line["index"],
                    posted_on=date.fromisoformat(line["posted_on"]),
                    description=line["description"],
                    amount=int(line["amount"]),
                    reference=line.get("reference"),
                    branch=line.get("branch"),
                    confidence=line.get("confidence"),
                    kind=LineKind(line["kind"]) if line.get("kind") else None,
                    section=line.get("section"),
                    installment=_installment_from(line.get("installment")),
                )
                for line in st["lines"]
            ),
            summary=StatementSummary(**summary) if summary else None,
            daily_balances=tuple(DailyBalance(date.fromisoformat(b["on"]), int(b["balance"])) for b in st["daily_balances"]),
            statement_number=st.get("statement_number"),
            source=st["source"],
            # Statements stored before st-0.2 have none of these: checking accounts, final, no sections.
            account_type=AccountType(st.get("account_type", AccountType.CHECKING.value)),
            provisional=bool(st.get("provisional", False)),
            section_totals=tuple(SectionTotal(t["section"], int(t["amount"])) for t in st.get("section_totals", ())),
            obligations=_obligations_from(st.get("obligations")),
        ),
        issues=tuple(
            Issue(IssueCode(i["code"]), i["message"], i.get("expected"), i.get("found"), _date_or_none(i.get("on"))) for i in payload["issues"]
        ),
    )


class SqliteStatementStore:
    """Payloads are sealed with the data key (G11); ids and the owner stay in clear for lookups."""

    def __init__(self, db: SqliteDatabase, cipher: FieldCipher) -> None:
        self._db = db
        self._cipher = cipher

    def add(self, stored: StoredStatement) -> bool:
        payload = self._cipher.seal(json.dumps(to_primitive(stored)), _statement_aad(stored.user_id, stored.statement_id))
        with self._db.lock:
            cursor = self._db.connection.execute(
                "INSERT OR IGNORE INTO statements (statement_id, user_id, payload) VALUES (?, ?, ?)",
                (stored.statement_id, stored.user_id, payload),
            )
            return cursor.rowcount == 1

    def get(self, user_id: str, statement_id: str) -> StoredStatement | None:
        row = self._db.fetchone(
            "SELECT user_id, statement_id, payload FROM statements WHERE user_id = ? AND statement_id = ?", (user_id, statement_id)
        )
        return self._open(row) if row else None

    def for_user(self, user_id: str) -> tuple[StoredStatement, ...]:
        rows = self._db.fetchall("SELECT user_id, statement_id, payload FROM statements WHERE user_id = ? ORDER BY sequence", (user_id,))
        return tuple(self._open(r) for r in rows)

    def _open(self, row: tuple) -> StoredStatement:
        user_id, statement_id, payload = row
        return _stored_statement_from(json.loads(self._cipher.open(payload, _statement_aad(user_id, statement_id))))


def _statement_aad(user_id: str, statement_id: str) -> str:
    return f"statements|{user_id}|{statement_id}"


def _transaction_aad(user_id: str, txn_id: str) -> str:
    return f"transactions|{user_id}|{txn_id}"


def _receipt_aad(user_id: str, receipt_id: str) -> str:
    return f"receipts|{user_id}|{receipt_id}"


class SqliteReceiptStore:
    """Payloads are sealed with the data key (G11); ids and the owner stay in clear for lookups."""

    def __init__(self, db: SqliteDatabase, cipher: FieldCipher) -> None:
        self._db = db
        self._cipher = cipher

    def add(self, receipt: StoredReceipt) -> bool:
        payload = self._cipher.seal(json.dumps(to_primitive(receipt)), _receipt_aad(receipt.user_id, receipt.receipt_id))
        with self._db.lock:
            cursor = self._db.connection.execute(
                "INSERT OR IGNORE INTO receipts (receipt_id, user_id, payload) VALUES (?, ?, ?)",
                (receipt.receipt_id, receipt.user_id, payload),
            )
            return cursor.rowcount == 1

    def get(self, user_id: str, receipt_id: str) -> StoredReceipt | None:
        row = self._db.fetchone("SELECT user_id, receipt_id, payload FROM receipts WHERE user_id = ? AND receipt_id = ?", (user_id, receipt_id))
        return self._open(row) if row else None

    def for_user(self, user_id: str) -> tuple[StoredReceipt, ...]:
        rows = self._db.fetchall("SELECT user_id, receipt_id, payload FROM receipts WHERE user_id = ? ORDER BY sequence", (user_id,))
        return tuple(self._open(r) for r in rows)

    def replace(self, receipt: StoredReceipt) -> bool:
        payload = self._cipher.seal(json.dumps(to_primitive(receipt)), _receipt_aad(receipt.user_id, receipt.receipt_id))
        with self._db.lock:
            cursor = self._db.connection.execute(
                "UPDATE receipts SET payload = ? WHERE user_id = ? AND receipt_id = ?", (payload, receipt.user_id, receipt.receipt_id)
            )
            return cursor.rowcount == 1

    def _open(self, row: tuple) -> StoredReceipt:
        user_id, receipt_id, payload = row
        return _receipt_from(json.loads(self._cipher.open(payload, _receipt_aad(user_id, receipt_id))))


def _receipt_from(payload: dict) -> StoredReceipt:
    return StoredReceipt(
        receipt_id=payload["receipt_id"],
        user_id=payload["user_id"],
        imported_at=datetime.fromisoformat(payload["imported_at"]),
        issuer=payload["issuer"],
        issued_on=date.fromisoformat(payload["issued_on"]) if payload.get("issued_on") else None,
        total=payload.get("total"),
        currency=payload["currency"],
        folio=payload.get("folio"),
        stamped=bool(payload["stamped"]),
        source=payload["source"],
        confidence=payload.get("confidence"),
        category=payload["category"],
        classifier=payload["classifier"],
        category_confidence=payload.get("category_confidence"),
        issues=tuple(
            ReceiptIssue(ReceiptIssueCode(i["code"]), i["message"], i.get("expected"), i.get("found")) for i in payload.get("issues", ())
        ),
        corrected=bool(payload.get("corrected", False)),  # receipts stored before corrections existed were never corrected
        payment=payload.get("payment", "unknown"),
    )


def _memory_aad(user_id: str, memory_id: str) -> str:
    return f"user_memory|{user_id}|{memory_id}"


def _open_declaration(cipher: FieldCipher, row: tuple) -> Declaration:
    """A stored version; its clear columns must say what the sealed payload says, or the row was edited around us."""
    memory_id, chain_id, version, user_id, type_, payload = row
    declaration = parse_declaration(json.loads(cipher.open(payload, _memory_aad(user_id, memory_id))), user_id)
    if (declaration.memory_id, declaration.chain_id, declaration.version, declaration.type.value) != (memory_id, chain_id, version, type_):
        raise FieldCipherError("a user_memory row does not match its sealed payload")
    return declaration


def _append_memory(conn: sqlite3.Connection, cipher: FieldCipher, declarations: Sequence[Declaration], expected_version: int) -> bool:
    """MemoryStore.append inside the caller's transaction, so a later step can add the audit and the proposal to it."""
    check_appended(declarations, expected_version)
    first = declarations[0]
    if any(conn.execute("SELECT 1 FROM user_memory WHERE memory_id = ?", (d.memory_id,)).fetchone() for d in declarations):
        raise IdCollision("generated identifier collision")
    if conn.execute("SELECT 1 FROM user_memory WHERE chain_id = ? AND user_id != ?", (first.chain_id, first.user_id)).fetchone():
        raise IdCollision("generated identifier collision")
    row = conn.execute("SELECT MAX(version) FROM user_memory WHERE user_id = ? AND chain_id = ?", (first.user_id, first.chain_id)).fetchone()
    if (row[0] or 0) != expected_version:
        return False
    if expected_version == 0 and conn.execute(
        "SELECT 1 FROM user_memory WHERE user_id = ? AND type = ?", (first.user_id, first.type.value)
    ).fetchone():
        return False  # the user already has a chain of this type
    conn.executemany(
        "INSERT INTO user_memory (memory_id, chain_id, version, user_id, type, payload) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (d.memory_id, d.chain_id, d.version, d.user_id, d.type.value,
             cipher.seal(json.dumps(declaration_record(d)), _memory_aad(d.user_id, d.memory_id)))
            for d in declarations
        ],
    )
    return True


class SqliteMemoryStore:
    """Declared memory (ADR-048), sealed with the data key; ids, owner, version and type stay in clear for lookups and
    for the uniqueness of a chain per user and type, which the database enforces as well."""

    def __init__(self, db: SqliteDatabase, cipher: FieldCipher) -> None:
        self._db = db
        self._cipher = cipher

    def for_user(self, user_id: str) -> tuple[Declaration, ...]:
        rows = self._db.fetchall(
            "SELECT memory_id, chain_id, version, user_id, type, payload FROM user_memory m WHERE user_id = ? "
            "ORDER BY (SELECT MIN(sequence) FROM user_memory c WHERE c.chain_id = m.chain_id), version",
            (user_id,),
        )
        return tuple(_open_declaration(self._cipher, row) for row in rows)

    def chain(self, user_id: str, chain_id: str) -> tuple[Declaration, ...]:
        rows = self._db.fetchall(
            "SELECT memory_id, chain_id, version, user_id, type, payload FROM user_memory WHERE user_id = ? AND chain_id = ? ORDER BY version",
            (user_id, chain_id),
        )
        return tuple(_open_declaration(self._cipher, row) for row in rows)

    def chain_of_type(self, user_id: str, type: MemoryType) -> tuple[Declaration, ...]:
        rows = self._db.fetchall(
            "SELECT memory_id, chain_id, version, user_id, type, payload FROM user_memory WHERE user_id = ? AND type = ? ORDER BY version",
            (user_id, type.value),
        )
        return tuple(_open_declaration(self._cipher, row) for row in rows)

    def append(self, declarations: Sequence[Declaration], expected_version: int) -> bool:
        with _account_transaction(self._db) as conn:
            return _append_memory(conn, self._cipher, declarations, expected_version)

    def delete_chain(self, user_id: str, chain_id: str) -> int:
        with self._db.lock:
            return self._db.connection.execute("DELETE FROM user_memory WHERE user_id = ? AND chain_id = ?", (user_id, chain_id)).rowcount


class SqliteConnectionStore:
    """Connections and their latest answers (ADR-047). The payload, which holds the secret (an MCP token or a bank
    link), is sealed with the data key like every personal column; ids and the owner stay in clear for lookups."""

    def __init__(self, db: SqliteDatabase, cipher: FieldCipher) -> None:
        self._db = db
        self._cipher = cipher

    def add(self, connection: Connection, secret: str | None) -> None:
        payload = self._seal(connection, secret)
        with self._db.lock:
            self._db.connection.execute(
                "INSERT INTO connections (connection_id, user_id, payload) VALUES (?, ?, ?)", (connection.connection_id, connection.user_id, payload)
            )

    def get(self, user_id: str, connection_id: str) -> Connection | None:
        found = self._row(user_id, connection_id)
        return found[0] if found else None

    def for_user(self, user_id: str) -> tuple[Connection, ...]:
        rows = self._db.fetchall("SELECT connection_id, payload FROM connections WHERE user_id = ? ORDER BY sequence", (user_id,))
        return tuple(self._open(user_id, cid, payload)[0] for cid, payload in rows)

    def update(self, connection: Connection) -> bool:
        with self._db.lock:
            row = self._db.connection.execute(
                "SELECT payload FROM connections WHERE user_id = ? AND connection_id = ?", (connection.user_id, connection.connection_id)
            ).fetchone()
            if row is None:
                return False
            secret = self._open(connection.user_id, connection.connection_id, row[0])[1]
            cursor = self._db.connection.execute(
                "UPDATE connections SET payload = ? WHERE user_id = ? AND connection_id = ?",
                (self._seal(connection, secret), connection.user_id, connection.connection_id),
            )
            return cursor.rowcount == 1

    def secret(self, user_id: str, connection_id: str) -> str | None:
        found = self._row(user_id, connection_id)
        return found[1] if found else None

    def put_results(self, user_id: str, connection_id: str, results: Sequence[ConnectionSnapshot]) -> None:
        with _account_transaction(self._db) as conn:
            conn.execute("DELETE FROM connection_results WHERE user_id = ? AND connection_id = ?", (user_id, connection_id))
            for r in results:
                aad = _aad("connection_results", user_id, f"{connection_id}|{r.tool}")
                conn.execute(
                    "INSERT INTO connection_results (connection_id, user_id, tool, payload) VALUES (?, ?, ?, ?)",
                    (connection_id, user_id, r.tool, self._cipher.seal(json.dumps(to_primitive(r)), aad)),
                )

    def results(self, user_id: str, connection_id: str) -> tuple[ConnectionSnapshot, ...]:
        rows = self._db.fetchall(
            "SELECT tool, payload FROM connection_results WHERE user_id = ? AND connection_id = ? ORDER BY sequence", (user_id, connection_id)
        )
        out = []
        for tool, payload in rows:
            p = json.loads(self._cipher.open(payload, _aad("connection_results", user_id, f"{connection_id}|{tool}")))
            out.append(ConnectionSnapshot(p["connection_id"], p["user_id"], p["tool"], datetime.fromisoformat(p["fetched_at"]), p["content"], bool(p["ok"])))
        return tuple(out)

    def remove(self, user_id: str, connection_id: str) -> bool:
        with _account_transaction(self._db) as conn:
            conn.execute("DELETE FROM connection_results WHERE user_id = ? AND connection_id = ?", (user_id, connection_id))
            return conn.execute("DELETE FROM connections WHERE user_id = ? AND connection_id = ?", (user_id, connection_id)).rowcount == 1

    def _row(self, user_id: str, connection_id: str) -> tuple[Connection, str | None] | None:
        row = self._db.fetchone("SELECT payload FROM connections WHERE user_id = ? AND connection_id = ?", (user_id, connection_id))
        return self._open(user_id, connection_id, row[0]) if row else None

    def _seal(self, connection: Connection, secret: str | None) -> str:
        payload = {"connection": to_primitive(connection), "secret": secret}
        return self._cipher.seal(json.dumps(payload), _aad("connections", connection.user_id, connection.connection_id))

    def _open(self, user_id: str, connection_id: str, sealed: str) -> tuple[Connection, str | None]:
        payload = json.loads(self._cipher.open(sealed, _aad("connections", user_id, connection_id)))
        return _connection_from(payload["connection"]), payload["secret"]


def _connection_from(p: dict) -> Connection:
    return Connection(
        connection_id=p["connection_id"],
        user_id=p["user_id"],
        kind=ConnectionKind(p["kind"]),
        name=p["name"],
        endpoint=p["endpoint"],
        created_at=datetime.fromisoformat(p["created_at"]),
        tools=tuple(
            RemoteTool(t["name"], t["description"], t["read_only_hint"], t["destructive_hint"], tuple(t["required_args"])) for t in p["tools"]
        ),
        enabled=tuple(p["enabled"]),
        last_synced_at=datetime.fromisoformat(p["last_synced_at"]) if p.get("last_synced_at") else None,
        state=p.get("state"),
    )


@dataclass(frozen=True, slots=True)
class SealedColumn:
    """One column sealed with the data key: how to read every row, rebuild its associated data and rewrite it.

    Literal statements only (no SQL built from strings, ASVS V1). The migration and the key check read this list,
    so a newly sealed column is added here and nowhere else."""

    table: str
    select: str  # rowid first, value last; the columns in between build the associated data
    update: str  # (value, rowid)
    aad: Callable[[tuple], str]


SEALED_COLUMNS: tuple[SealedColumn, ...] = (
    SealedColumn(
        "statements", "SELECT rowid, user_id, statement_id, payload FROM statements ORDER BY rowid",
        "UPDATE statements SET payload = ? WHERE rowid = ?", lambda r: _statement_aad(r[1], r[2]),
    ),
    SealedColumn(
        "transactions", "SELECT rowid, user_id, txn_id, payload FROM transactions ORDER BY rowid",
        "UPDATE transactions SET payload = ? WHERE rowid = ?", lambda r: _transaction_aad(r[1], r[2]),
    ),
    SealedColumn(
        "receipts", "SELECT rowid, user_id, receipt_id, payload FROM receipts ORDER BY rowid",
        "UPDATE receipts SET payload = ? WHERE rowid = ?", lambda r: _receipt_aad(r[1], r[2]),
    ),
    SealedColumn(
        "connections", "SELECT rowid, user_id, connection_id, payload FROM connections ORDER BY rowid",
        "UPDATE connections SET payload = ? WHERE rowid = ?", lambda r: _aad("connections", r[1], r[2]),
    ),
    SealedColumn(
        "connection_results", "SELECT rowid, user_id, connection_id, tool, payload FROM connection_results ORDER BY rowid",
        "UPDATE connection_results SET payload = ? WHERE rowid = ?", lambda r: _aad("connection_results", r[1], f"{r[2]}|{r[3]}"),
    ),
    SealedColumn(
        "user_memory", "SELECT rowid, user_id, memory_id, payload FROM user_memory ORDER BY rowid",
        "UPDATE user_memory SET payload = ? WHERE rowid = ?", lambda r: _memory_aad(r[1], r[2]),
    ),
    SealedColumn(
        "memory_state", "SELECT rowid, user_id, user_id, payload FROM memory_state ORDER BY rowid",
        "UPDATE memory_state SET payload = ? WHERE rowid = ?", lambda r: _aad("memory_state", r[1], r[2]),
    ),
    SealedColumn(
        "memory_proposals", "SELECT rowid, user_id, proposal_id, payload FROM memory_proposals ORDER BY rowid",
        "UPDATE memory_proposals SET payload = ? WHERE rowid = ?", lambda r: _aad("memory_proposals", r[1], r[2]),
    ),
    SealedColumn(
        "user_profiles", "SELECT rowid, user_id, payload FROM user_profiles ORDER BY rowid",
        "UPDATE user_profiles SET payload = ? WHERE rowid = ?", lambda r: _aad("user_profiles", r[1], r[1]),
    ),
    SealedColumn(
        "user_accounts", "SELECT rowid, user_id, payload FROM user_accounts ORDER BY rowid",
        "UPDATE user_accounts SET payload = ? WHERE rowid = ?", lambda r: _aad("user_accounts", r[1], r[1]),
    ),
    SealedColumn(
        "proposals", "SELECT rowid, user_id, proposal_id, payload FROM proposals ORDER BY rowid",
        "UPDATE proposals SET payload = ? WHERE rowid = ?", lambda r: _aad("proposals", r[1], r[2]),
    ),
    SealedColumn(
        "authorizations", "SELECT rowid, user_id, authorization_id, payload FROM authorizations ORDER BY rowid",
        "UPDATE authorizations SET payload = ? WHERE rowid = ?", lambda r: _aad("authorizations", r[1], r[2]),
    ),
    SealedColumn(
        "savings_rules", "SELECT rowid, user_id, rule_id, payload FROM savings_rules ORDER BY rowid",
        "UPDATE savings_rules SET payload = ? WHERE rowid = ?", lambda r: _aad("savings_rules", r[1], r[2]),
    ),
    SealedColumn(
        "audit_events", "SELECT rowid, user_id, event_id, record FROM audit_events ORDER BY rowid",
        "UPDATE audit_events SET record = ? WHERE rowid = ?", lambda r: _aad("audit_events", r[1], r[2]),
    ),
    SealedColumn(
        "investment_links", "SELECT rowid, user_id, payload FROM investment_links ORDER BY rowid",
        "UPDATE investment_links SET payload = ? WHERE rowid = ?", lambda r: _aad("investment_links", r[1], r[1]),
    ),
    SealedColumn(
        "investment_snapshots", "SELECT rowid, user_id, snapshot_id, payload FROM investment_snapshots ORDER BY rowid",
        "UPDATE investment_snapshots SET payload = ? WHERE rowid = ?", lambda r: _aad("investment_snapshots", r[1], r[2]),
    ),
    SealedColumn(
        "investment_documents", "SELECT rowid, user_id, document_id, payload FROM investment_documents ORDER BY rowid",
        "UPDATE investment_documents SET payload = ? WHERE rowid = ?", lambda r: _aad("investment_documents", r[1], r[2]),
    ),
)

KEY_CHECK_AAD = "meta|key_check|key_check"
KEY_CHECK_TEXT = "neural-ledger data key check"


def write_key_check(conn: sqlite3.Connection, cipher: FieldCipher) -> None:
    conn.execute(
        "INSERT INTO meta (name, value) VALUES ('key_check', ?) ON CONFLICT(name) DO UPDATE SET value = excluded.value",
        (cipher.seal(KEY_CHECK_TEXT, KEY_CHECK_AAD),),
    )


def verify_data_key(db: SqliteDatabase, cipher: FieldCipher) -> None:
    """Refuse a key that does not open this database, before anything is written with it.

    The database keeps a sealed key check in `meta`. A database without one (created before it existed) is
    probed with its first sealed value per column; then the check is written, so the next start is one read."""
    with db.lock:
        conn = db.connection
        row = conn.execute("SELECT value FROM meta WHERE name = 'key_check'").fetchone()
        try:
            if row is not None:
                if cipher.open(row[0], KEY_CHECK_AAD) != KEY_CHECK_TEXT:
                    raise FieldCipherError("key check")
                return
            for column in SEALED_COLUMNS:
                for record in conn.execute(column.select):
                    if cipher.is_sealed(record[-1]):
                        cipher.open(record[-1], column.aad(record))
                        break
        except FieldCipherError:
            raise WrongDataKey(
                "the data key does not open this database: set the key it was written with, or run "
                "`neural-ledger migrate-data` to move it to the new key"
            ) from None
        write_key_check(conn, cipher)


def _installment_info_from(payload: dict | None) -> InstallmentInfo | None:
    if not payload:
        return None
    return InstallmentInfo(
        plan_id=payload["plan_id"],
        installment_number=payload["installment_number"],
        installment_total=payload["installment_total"],
        original_amount=payload["original_amount"],
        monthly_rate=_decimal_or_none(payload.get("monthly_rate")),
    )


def _posted_from(payload: dict) -> PostedTransaction:
    t = payload["transaction"]
    return PostedTransaction(
        user_id=payload["user_id"],
        currency=payload["currency"],
        transaction=Transaction(
            txn_id=t["txn_id"],
            account_id=t["account_id"],
            date=date.fromisoformat(t["date"]),
            amount=int(t["amount"]),
            merchant_raw=t["merchant_raw"],
            category=t["category"],
            kind=TransactionKind(t["kind"]),
            installment=_installment_info_from(t.get("installment")),
        ),
        statement_id=payload["statement_id"],
        line_index=int(payload["line_index"]),
        classifier=payload["classifier"],
        confidence=payload["confidence"],
    )


class SqliteTransactionStore:
    """Payloads are sealed with the data key (G11); the owner, id and posting date stay in clear for lookups and order."""

    def __init__(self, db: SqliteDatabase, cipher: FieldCipher) -> None:
        self._db = db
        self._cipher = cipher

    def add(self, posted: Sequence[PostedTransaction]) -> int:
        rows = [
            (
                p.transaction.txn_id,
                p.user_id,
                p.transaction.date.isoformat(),
                self._cipher.seal(json.dumps(to_primitive(p)), _transaction_aad(p.user_id, p.transaction.txn_id)),
            )
            for p in posted
        ]
        with self._db.lock:
            before = self._db.connection.total_changes
            self._db.connection.execute("BEGIN")
            try:
                self._db.connection.executemany(
                    "INSERT OR IGNORE INTO transactions (txn_id, user_id, posted_on, payload) VALUES (?, ?, ?, ?)", rows
                )
                self._db.connection.execute("COMMIT")
            except BaseException:
                self._db.connection.execute("ROLLBACK")
                raise
            return self._db.connection.total_changes - before

    def for_user(self, user_id: str) -> tuple[PostedTransaction, ...]:
        rows = self._db.fetchall("SELECT txn_id, payload FROM transactions WHERE user_id = ? ORDER BY posted_on, sequence", (user_id,))
        return tuple(_posted_from(json.loads(self._cipher.open(payload, _transaction_aad(user_id, txn_id)))) for txn_id, payload in rows)

    def get(self, user_id: str, txn_id: str) -> PostedTransaction | None:
        row = self._db.fetchone("SELECT payload FROM transactions WHERE user_id = ? AND txn_id = ?", (user_id, txn_id))
        return None if row is None else self._open(user_id, txn_id, row[0])

    def has_transactions(self, user_id: str) -> bool:
        return self._db.fetchone("SELECT 1 FROM transactions WHERE user_id = ? LIMIT 1", (user_id,)) is not None

    def _open(self, user_id: str, txn_id: str, payload: str) -> PostedTransaction:
        return _open_transaction(self._cipher, user_id, txn_id, payload)


def _open_transaction(cipher: FieldCipher, user_id: str, txn_id: str, payload: str) -> PostedTransaction:
    return _posted_from(json.loads(cipher.open(payload, _transaction_aad(user_id, txn_id))))


class SqliteSavingsRuleStore:
    """Rules created by the simulated sandbox bank, durable across restarts like the audit log; sealed like it too."""

    def __init__(self, db: SqliteDatabase, cipher: FieldCipher) -> None:
        self._db = db
        self._cipher = cipher

    def add(self, rule: SavingsRule) -> None:
        payload = self._cipher.seal(json.dumps(to_primitive(rule)), _aad("savings_rules", rule.user_id, rule.rule_id))
        with self._db.lock:
            self._db.connection.execute(
                "INSERT INTO savings_rules (rule_id, user_id, payload) VALUES (?, ?, ?)", (rule.rule_id, rule.user_id, payload)
            )

    def count(self) -> int:
        row = self._db.fetchone("SELECT COUNT(*) FROM savings_rules")
        return row[0] if row else 0

    def next_number(self) -> int:
        row = self._db.fetchone(
            "SELECT COALESCE(MAX(CAST(substr(rule_id, 6) AS INTEGER)), 0) FROM savings_rules WHERE rule_id LIKE 'rule\\_%' ESCAPE '\\'"
        )
        return (row[0] if row else 0) + 1

    def for_user(self, user_id: str) -> tuple[SavingsRule, ...]:
        rows = self._db.fetchall("SELECT rule_id, payload FROM savings_rules WHERE user_id = ? ORDER BY sequence", (user_id,))
        return tuple(_rule_from(json.loads(self._cipher.open(payload, _aad("savings_rules", user_id, rule_id)))) for rule_id, payload in rows)


class SqliteActionRepository:
    """Proposals and authorizations, sealed with the data key. The owner is a clear column: it binds each sealed
    payload to its user (associated data) and lets an account deletion find them."""

    def __init__(self, db: SqliteDatabase, cipher: FieldCipher) -> None:
        self._db = db
        self._cipher = cipher

    def _seal_proposal(self, proposal: Proposal) -> str:
        return self._cipher.seal(json.dumps(to_primitive(proposal)), _aad("proposals", proposal.user_id, proposal.proposal_id))

    def _open_proposal(self, row: tuple) -> Proposal:
        proposal_id, user_id, payload = row
        return _proposal_from(json.loads(self._cipher.open(payload, _aad("proposals", user_id, proposal_id))))

    def _open_authorization(self, row: tuple) -> Authorization:
        authorization_id, user_id, payload, consumed_at = row
        return _authorization_from(json.loads(self._cipher.open(payload, _aad("authorizations", user_id, authorization_id))), consumed_at)

    def add_proposal(self, proposal: Proposal) -> None:
        with self._db.lock:
            self._db.connection.execute(
                "INSERT INTO proposals (proposal_id, user_id, session_id, payload) VALUES (?, ?, ?, ?)",
                (proposal.proposal_id, proposal.user_id, proposal.session_id, self._seal_proposal(proposal)),
            )

    def get_proposal(self, proposal_id: str) -> Proposal | None:
        row = self._db.fetchone("SELECT proposal_id, user_id, payload FROM proposals WHERE proposal_id = ?", (proposal_id,))
        return self._open_proposal(row) if row else None

    def update_proposal(self, proposal: Proposal) -> None:
        with self._db.lock:
            self._db.connection.execute(
                "UPDATE proposals SET payload = ? WHERE proposal_id = ? AND user_id = ?",
                (self._seal_proposal(proposal), proposal.proposal_id, proposal.user_id),
            )

    def add_authorization(self, authorization: Authorization) -> None:
        payload = to_primitive(authorization)
        payload.pop("consumed_at", None)
        sealed = self._cipher.seal(json.dumps(payload), _aad("authorizations", authorization.user_id, authorization.authorization_id))
        with self._db.lock:
            self._db.connection.execute(
                "INSERT INTO authorizations (authorization_id, user_id, session_id, payload, consumed_at) VALUES (?, ?, ?, ?, NULL)",
                (authorization.authorization_id, authorization.user_id, authorization.session_id, sealed),
            )

    def get_authorization(self, authorization_id: str) -> Authorization | None:
        row = self._db.fetchone(
            "SELECT authorization_id, user_id, payload, consumed_at FROM authorizations WHERE authorization_id = ?", (authorization_id,)
        )
        return self._open_authorization(row) if row else None

    def consume_authorization(self, authorization_id: str, at: datetime) -> bool:
        with self._db.lock:
            cursor = self._db.connection.execute(
                "UPDATE authorizations SET consumed_at = ? WHERE authorization_id = ? AND consumed_at IS NULL",
                (at.isoformat(), authorization_id),
            )
            return cursor.rowcount == 1

    def for_session(self, session_id: str) -> tuple[tuple[Proposal, ...], tuple[Authorization, ...]]:
        proposals = self._db.fetchall("SELECT proposal_id, user_id, payload FROM proposals WHERE session_id = ?", (session_id,))
        auths = self._db.fetchall(
            "SELECT authorization_id, user_id, payload, consumed_at FROM authorizations WHERE session_id = ?", (session_id,)
        )
        return tuple(self._open_proposal(r) for r in proposals), tuple(self._open_authorization(r) for r in auths)

    def for_user(self, user_id: str) -> tuple[tuple[Proposal, ...], tuple[Authorization, ...]]:
        proposals = self._db.fetchall("SELECT proposal_id, user_id, payload FROM proposals WHERE user_id = ? ORDER BY rowid", (user_id,))
        auths = self._db.fetchall(
            "SELECT authorization_id, user_id, payload, consumed_at FROM authorizations WHERE user_id = ? ORDER BY rowid", (user_id,)
        )
        return tuple(self._open_proposal(r) for r in proposals), tuple(self._open_authorization(r) for r in auths)


def _open_record(cipher: FieldCipher, row: tuple) -> dict:
    """An audit record (event_id, user_id, sealed record): the hash chain lives inside it, so verifying the chain
    needs the key, and the database shows no hash to test a guessed event against."""
    event_id, user_id, record = row
    return json.loads(cipher.open(record, _aad("audit_events", user_id, event_id)))


def _append_audit(conn: sqlite3.Connection, cipher: FieldCipher, draft: AuditDraft) -> AuditEvent:
    """Seal the draft onto the chain. The hash covers the plaintext record (domain/audit/events.py), exactly as an
    export shows it; the stored row is that record, with its hashes, sealed with the data key."""
    row = conn.execute("SELECT sequence, event_id, user_id, record FROM audit_events ORDER BY sequence DESC LIMIT 1").fetchone()
    sequence, prev = (row[0] + 1, _open_record(cipher, row[1:])["event_hash"]) if row else (1, GENESIS_HASH)
    event = seal(draft, sequence, prev)
    record = cipher.seal(json.dumps(event.to_record()), _aad("audit_events", draft.user_id, draft.event_id))
    conn.execute(
        "INSERT INTO audit_events (sequence, event_id, user_id, session_id, record) VALUES (?, ?, ?, ?, ?)",
        (sequence, draft.event_id, draft.user_id, draft.session_id, record),
    )
    return event


@contextmanager
def _account_transaction(db: SqliteDatabase) -> Iterator[sqlite3.Connection]:
    with db.lock:
        conn = db.connection
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise


class SqliteAccountWrites:
    def __init__(self, db: SqliteDatabase, cipher: FieldCipher) -> None:
        self._db = db
        self._cipher = cipher

    def register(self, account: UserAccount, profile: UserProfile, session: Session, events: Sequence[AuditDraft]) -> bool:
        if profile.user_id != account.user_id or session.user_id != account.user_id or any(
            event.user_id != account.user_id for event in events
        ):
            raise ValueError("account ownership mismatch")
        with _account_transaction(self._db) as conn:
            if conn.execute("SELECT 1 FROM user_accounts WHERE email_index = ?", (email_index(self._cipher, account.email),)).fetchone():
                return False
            if (
                conn.execute("SELECT 1 FROM user_accounts WHERE user_id = ?", (account.user_id,)).fetchone()
                or conn.execute("SELECT 1 FROM user_profiles WHERE user_id = ?", (account.user_id,)).fetchone()
            ):
                raise IdCollision("generated identifier collision")
            self._check_session_and_events(conn, session, events)
            conn.execute(
                "INSERT INTO user_accounts (user_id, email_index, payload, sample_data) VALUES (?, ?, ?, ?)",
                _account_row(self._cipher, account),
            )
            conn.execute(
                "INSERT INTO user_profiles (user_id, payload) VALUES (?, ?)", (profile.user_id, _seal_profile(self._cipher, profile))
            )
            conn.execute(
                "INSERT INTO sessions (session_ref, token_hash, user_id, payload, revoked_at) VALUES (?, ?, ?, ?, ?)",
                _session_row(session),
            )
            for event in events:
                _append_audit(conn, self._cipher, event)
            return True

    def open_session(self, session: Session, events: Sequence[AuditDraft]) -> None:
        with _account_transaction(self._db) as conn:
            self._check_session_and_events(conn, session, events)
            conn.execute(
                "INSERT INTO sessions (session_ref, token_hash, user_id, payload, revoked_at) VALUES (?, ?, ?, ?, ?)",
                _session_row(session),
            )
            for event in events:
                _append_audit(conn, self._cipher, event)

    def close_session(self, session: Session, at: datetime, events: Sequence[AuditDraft]) -> bool:
        with _account_transaction(self._db) as conn:
            cursor = conn.execute(
                "UPDATE sessions SET revoked_at = ? WHERE session_ref = ? AND token_hash = ? AND revoked_at IS NULL",
                (at.isoformat(), session.session_ref, session.token_hash),
            )
            if cursor.rowcount == 0:
                return False
            self._check_events(conn, events)
            for event in events:
                _append_audit(conn, self._cipher, event)
            return True

    def set_sample_data(self, user_id: str, enabled: bool, events: Sequence[AuditDraft]) -> bool:
        with _account_transaction(self._db) as conn:
            cursor = conn.execute(
                "UPDATE user_accounts SET sample_data = ? WHERE user_id = ?", (int(enabled), user_id)
            )
            if cursor.rowcount == 0:
                return False
            self._check_events(conn, events)
            for event in events:
                _append_audit(conn, self._cipher, event)
            return True

    def update_profile(self, expected: UserProfile, updated: UserProfile, events: Sequence[AuditDraft]) -> bool:
        if updated.user_id != expected.user_id or any(event.user_id != expected.user_id for event in events):
            raise ValueError("profile ownership mismatch")
        # Raw connection only: the store and audit-log methods take db.lock, which this transaction already holds.
        with _account_transaction(self._db) as conn:
            row = conn.execute("SELECT payload FROM user_profiles WHERE user_id = ?", (expected.user_id,)).fetchone()
            if row is None or _open_profile(self._cipher, expected.user_id, row[0]) != expected:
                return False
            self._check_events(conn, events)
            conn.execute(
                "UPDATE user_profiles SET payload = ? WHERE user_id = ?", (_seal_profile(self._cipher, updated), updated.user_id)
            )
            for event in events:
                _append_audit(conn, self._cipher, event)
            return True

    @staticmethod
    def _check_events(conn: sqlite3.Connection, events: Sequence[AuditDraft]) -> None:
        ids = [event.event_id for event in events]
        if len(ids) != len(set(ids)) or any(
            conn.execute("SELECT 1 FROM audit_events WHERE event_id = ?", (event_id,)).fetchone()
            for event_id in ids
        ):
            raise IdCollision("generated identifier collision")

    @classmethod
    def _check_session_and_events(cls, conn: sqlite3.Connection, session: Session, events: Sequence[AuditDraft]) -> None:
        if (
            conn.execute("SELECT 1 FROM sessions WHERE session_ref = ? OR token_hash = ?", (session.session_ref, session.token_hash)).fetchone()
        ):
            raise IdCollision("generated identifier collision")
        cls._check_events(conn, events)


def _check_transaction_change(expected: PostedTransaction, updated: PostedTransaction, events: Sequence[AuditDraft]) -> None:
    owner = expected.user_id
    if (owner, expected.transaction.txn_id) != (updated.user_id, updated.transaction.txn_id) or any(e.user_id != owner for e in events):
        raise ValueError("transaction ownership mismatch")


class SqliteTransactionWrites:
    """A transaction change and its audit events in one SQLite transaction (ADR-023)."""

    def __init__(self, db: SqliteDatabase, cipher: FieldCipher) -> None:
        self._db = db
        self._cipher = cipher

    def update_transaction(self, expected: PostedTransaction, updated: PostedTransaction, events: Sequence[AuditDraft]) -> bool:
        _check_transaction_change(expected, updated, events)
        user_id, txn_id = expected.user_id, expected.transaction.txn_id
        # Raw connection only: the store and audit-log methods take db.lock, which this transaction already holds.
        with _account_transaction(self._db) as conn:
            row = conn.execute("SELECT payload FROM transactions WHERE user_id = ? AND txn_id = ?", (user_id, txn_id)).fetchone()
            if row is None or _open_transaction(self._cipher, user_id, txn_id, row[0]) != expected:
                return False
            SqliteAccountWrites._check_events(conn, events)
            conn.execute(
                "UPDATE transactions SET payload = ? WHERE user_id = ? AND txn_id = ?",
                (self._cipher.seal(json.dumps(to_primitive(updated)), _transaction_aad(user_id, txn_id)), user_id, txn_id),
            )
            for event in events:
                _append_audit(conn, self._cipher, event)
            return True


def _check_investment_write(
    expected: InvestmentLink | None, link: InvestmentLink, snapshot: InvestmentSnapshot | None, events: Sequence[AuditDraft]
) -> None:
    owner = link.user_id
    if (expected is not None and expected.user_id != owner) or (snapshot is not None and snapshot.user_id != owner) or any(e.user_id != owner for e in events):
        raise ValueError("investment ownership mismatch")


def _link_payload(link: InvestmentLink) -> str:
    """Field by field: the email and the token are written here and nowhere else, and only sealed."""
    return json.dumps({
        "user_id": link.user_id, "provider": link.provider, "adapter": link.adapter, "email": link.email,
        "token": link.token, "linked_at": link.linked_at.isoformat(), "expired": link.expired,
    })


def _link_from(payload: dict) -> InvestmentLink:
    return InvestmentLink(
        payload["user_id"], payload["provider"], payload["adapter"], payload["email"], payload["token"],
        datetime.fromisoformat(payload["linked_at"]), payload["expired"],
    )


def _snapshot_from(payload: dict) -> InvestmentSnapshot:
    goals = tuple(InvestmentGoal(g["goal_id"], g["name"], g["value"], g["deposited"]) for g in payload["goals"])
    return InvestmentSnapshot(
        payload["user_id"], payload["provider"], payload["currency"], datetime.fromisoformat(payload["fetched_at"]), goals, payload["synthetic"]
    )


def _document_payload(d: StoredInvestmentDocument) -> str:
    """Shares and values per share as exact decimal text; rows as arrays, so a long certificate stays small."""
    return json.dumps({
        "document_id": d.document_id, "user_id": d.user_id, "provider": d.provider, "kind": d.kind.value,
        "imported_at": d.imported_at.isoformat(), "as_of": d.as_of.isoformat(), "total": d.total,
        "positions": [[p.fund, p.series, str(p.shares), str(p.share_value), p.balance] for p in d.positions],
        "movements": [
            [m.day.isoformat(), m.goal, m.fund, m.series, str(m.shares_in), str(m.shares_out), str(m.share_value),
             str(m.shares_after), m.pesos_in, m.pesos_out, m.internal, m.pesos_after]
            for m in d.movements
        ],
    })


def _document_from(payload: dict) -> StoredInvestmentDocument:
    return StoredInvestmentDocument(
        document_id=payload["document_id"],
        user_id=payload["user_id"],
        provider=payload["provider"],
        kind=InvestmentDocumentKind(payload["kind"]),
        imported_at=datetime.fromisoformat(payload["imported_at"]),
        as_of=date.fromisoformat(payload["as_of"]),
        positions=tuple(FundPosition(f, s, Decimal(sh), Decimal(v), b) for f, s, sh, v, b in payload["positions"]),
        total=payload["total"],
        movements=tuple(
            FundMovement(date.fromisoformat(d), g, f, s, Decimal(i), Decimal(o), Decimal(v), Decimal(a), pi, po, internal, pa)
            for d, g, f, s, i, o, v, a, pi, po, internal, pa in payload["movements"]
        ),
    )


class SqliteInvestmentStore:
    """Investment links, synced snapshots and imported documents (ADR-044), sealed with the data key. The owner is a
    clear column: it binds each sealed payload to its user (associated data) and lets an account deletion find them. A
    write commits with its audit events in one SQLite transaction; an unlink or a document removal also truncates the
    WAL, so no old page keeps the token or the rows."""

    def __init__(self, db: SqliteDatabase, cipher: FieldCipher) -> None:
        self._db = db
        self._cipher = cipher

    def _open_link(self, user_id: str, payload: str) -> InvestmentLink:
        return _link_from(json.loads(self._cipher.open(payload, _aad("investment_links", user_id, user_id))))

    def link(self, user_id: str) -> InvestmentLink | None:
        row = self._db.fetchone("SELECT payload FROM investment_links WHERE user_id = ?", (user_id,))
        return self._open_link(user_id, row[0]) if row else None

    def latest(self, user_id: str) -> InvestmentSnapshot | None:
        row = self._db.fetchone(
            "SELECT snapshot_id, payload FROM investment_snapshots WHERE user_id = ? ORDER BY sequence DESC LIMIT 1", (user_id,)
        )
        if row is None:
            return None
        return _snapshot_from(json.loads(self._cipher.open(row[1], _aad("investment_snapshots", user_id, row[0]))))

    def save(
        self, expected: InvestmentLink | None, link: InvestmentLink, snapshot: InvestmentSnapshot | None, events: Sequence[AuditDraft]
    ) -> bool:
        _check_investment_write(expected, link, snapshot, events)
        user_id = link.user_id
        # Raw connection only: the audit-log methods take db.lock, which this transaction already holds.
        with _account_transaction(self._db) as conn:
            row = conn.execute("SELECT payload FROM investment_links WHERE user_id = ?", (user_id,)).fetchone()
            if (self._open_link(user_id, row[0]) if row else None) != expected:
                return False
            SqliteAccountWrites._check_events(conn, events)
            conn.execute(
                "INSERT INTO investment_links (user_id, payload) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET payload = excluded.payload",
                (user_id, self._cipher.seal(_link_payload(link), _aad("investment_links", user_id, user_id))),
            )
            if snapshot is not None:
                sealed = self._cipher.seal(json.dumps(to_primitive(snapshot)), _aad("investment_snapshots", user_id, snapshot.snapshot_id))
                conn.execute("INSERT INTO investment_snapshots (snapshot_id, user_id, payload) VALUES (?, ?, ?)", (snapshot.snapshot_id, user_id, sealed))
                conn.execute(
                    "DELETE FROM investment_snapshots WHERE user_id = ? AND sequence NOT IN "
                    "(SELECT sequence FROM investment_snapshots WHERE user_id = ? ORDER BY sequence DESC LIMIT ?)",
                    (user_id, user_id, MAX_SNAPSHOTS),
                )
            for event in events:
                _append_audit(conn, self._cipher, event)
            return True

    def remove(self, user_id: str, events: Sequence[AuditDraft]) -> int:
        if any(e.user_id != user_id for e in events):
            raise ValueError("investment ownership mismatch")
        with _account_transaction(self._db) as conn:
            if conn.execute("SELECT 1 FROM investment_links WHERE user_id = ?", (user_id,)).fetchone() is None:
                return 0
            SqliteAccountWrites._check_events(conn, events)
            removed = conn.execute("DELETE FROM investment_links WHERE user_id = ?", (user_id,)).rowcount
            removed += conn.execute("DELETE FROM investment_snapshots WHERE user_id = ?", (user_id,)).rowcount
            for event in events:
                _append_audit(conn, self._cipher, event)
        with self._db.lock:
            self._db.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return removed

    def add_document(self, document: StoredInvestmentDocument, events: Sequence[AuditDraft]) -> bool:
        user_id = document.user_id
        if any(e.user_id != user_id for e in events):
            raise ValueError("investment ownership mismatch")
        with _account_transaction(self._db) as conn:
            if conn.execute(
                "SELECT 1 FROM investment_documents WHERE user_id = ? AND document_id = ?", (user_id, document.document_id)
            ).fetchone():
                return False
            SqliteAccountWrites._check_events(conn, events)
            sealed = self._cipher.seal(_document_payload(document), _aad("investment_documents", user_id, document.document_id))
            conn.execute(
                "INSERT INTO investment_documents (document_id, user_id, payload) VALUES (?, ?, ?)", (document.document_id, user_id, sealed)
            )
            conn.execute(
                "DELETE FROM investment_documents WHERE user_id = ? AND sequence NOT IN "
                "(SELECT sequence FROM investment_documents WHERE user_id = ? ORDER BY sequence DESC LIMIT ?)",
                (user_id, user_id, MAX_DOCUMENTS),
            )
            for event in events:
                _append_audit(conn, self._cipher, event)
            return True

    def documents(self, user_id: str) -> tuple[StoredInvestmentDocument, ...]:
        rows = self._db.fetchall("SELECT document_id, payload FROM investment_documents WHERE user_id = ? ORDER BY sequence", (user_id,))
        return tuple(
            _document_from(json.loads(self._cipher.open(payload, _aad("investment_documents", user_id, document_id))))
            for document_id, payload in rows
        )

    def remove_documents(self, user_id: str, events: Sequence[AuditDraft]) -> int:
        if any(e.user_id != user_id for e in events):
            raise ValueError("investment ownership mismatch")
        with _account_transaction(self._db) as conn:
            removed = conn.execute("SELECT COUNT(*) FROM investment_documents WHERE user_id = ?", (user_id,)).fetchone()[0]
            if not removed:
                return 0
            SqliteAccountWrites._check_events(conn, events)
            conn.execute("DELETE FROM investment_documents WHERE user_id = ?", (user_id,))
            for event in events:
                _append_audit(conn, self._cipher, event)
        with self._db.lock:
            self._db.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return removed


def _account_exists(conn: sqlite3.Connection, user_id: str) -> bool:
    """Checked inside every memory write: a request authenticated before its account was deleted recreates nothing,
    and a shared persona, which has no account row, is never writable."""
    return conn.execute("SELECT 1 FROM user_accounts WHERE user_id = ?", (user_id,)).fetchone() is not None


def _memory_state(conn: sqlite3.Connection, cipher: FieldCipher, user_id: str) -> MemoryState:
    row = conn.execute("SELECT payload FROM memory_state WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        return MemoryState(user_id)
    return parse_state(json.loads(cipher.open(row[0], _aad("memory_state", user_id, user_id))), user_id)


def _put_memory_state(conn: sqlite3.Connection, cipher: FieldCipher, state: MemoryState) -> None:
    conn.execute(
        "INSERT INTO memory_state (user_id, payload) VALUES (?, ?) ON CONFLICT (user_id) DO UPDATE SET payload = excluded.payload",
        (state.user_id, cipher.seal(json.dumps(state_record(state)), _aad("memory_state", state.user_id, state.user_id))),
    )


def _memory_proposal(conn: sqlite3.Connection, cipher: FieldCipher, user_id: str, proposal_id: str) -> MemoryProposal | None:
    row = conn.execute("SELECT payload FROM memory_proposals WHERE proposal_id = ? AND user_id = ?", (proposal_id, user_id)).fetchone()
    if row is None:
        return None
    proposal = parse_proposal(json.loads(cipher.open(row[0], _aad("memory_proposals", user_id, proposal_id))), user_id)
    if proposal.proposal_id != proposal_id:
        raise FieldCipherError("a memory_proposals row does not match its sealed payload")
    return proposal


def _put_memory_proposal(conn: sqlite3.Connection, cipher: FieldCipher, proposal: MemoryProposal, *, insert: bool) -> None:
    payload = cipher.seal(json.dumps(proposal_record(proposal)), _aad("memory_proposals", proposal.user_id, proposal.proposal_id))
    if insert:
        conn.execute("INSERT INTO memory_proposals (proposal_id, user_id, payload) VALUES (?, ?, ?)", (proposal.proposal_id, proposal.user_id, payload))
    elif conn.execute(
        "UPDATE memory_proposals SET payload = ? WHERE proposal_id = ? AND user_id = ?", (payload, proposal.proposal_id, proposal.user_id)
    ).rowcount != 1:
        raise RuntimeError("proposal changed during a memory write")


def _invalidate_memory_proposals(conn: sqlite3.Connection, cipher: FieldCipher, user_id: str) -> int:
    count = 0
    for (proposal_id,) in conn.execute("SELECT proposal_id FROM memory_proposals WHERE user_id = ? ORDER BY proposal_id", (user_id,)).fetchall():
        proposal = _memory_proposal(conn, cipher, user_id, proposal_id)
        if proposal is not None and proposal.state is ProposalState.PENDING:
            _put_memory_proposal(conn, cipher, replace(proposal, state=ProposalState.INVALIDATED), insert=False)
            count += 1
    return count


def _check_memory_events(conn: sqlite3.Connection, owner: str, events: Sequence[AuditDraft]) -> None:
    if any(event.user_id != owner for event in events):
        raise ValueError("memory event ownership mismatch")
    SqliteAccountWrites._check_events(conn, events)


class SqliteMemoryWrites:
    """MemoryWrites in one SQLite transaction each. Raw connection only: the store and audit-log methods take
    db.lock, which the transaction already holds (the lock is not reentrant)."""

    def __init__(self, db: SqliteDatabase, cipher: FieldCipher) -> None:
        self._db = db
        self._cipher = cipher

    def state(self, user_id: str) -> MemoryState:
        with self._db.lock:
            return _memory_state(self._db.connection, self._cipher, user_id)

    def proposal(self, user_id: str, proposal_id: str) -> MemoryProposal | None:
        with self._db.lock:
            return _memory_proposal(self._db.connection, self._cipher, user_id, proposal_id)

    def set_consent(self, user_id: str, requested: Consent, event: AuditDraft) -> MemoryWriteResult:
        with _account_transaction(self._db) as conn:
            before = _memory_state(conn, self._cipher, user_id)
            if not _account_exists(conn, user_id):
                return MemoryWriteResult(WriteOutcome.NOT_WRITABLE, before)
            after = with_consent(before, requested)
            if after == before:
                return MemoryWriteResult(WriteOutcome.DONE, before, changed=False)
            invalidated = 0
            if after.consent is Consent.REVOKED:
                invalidated = _invalidate_memory_proposals(conn, self._cipher, user_id)
            _put_memory_state(conn, self._cipher, after)
            consent_event = replace(event, detail=consent_detail(before, after))
            _check_memory_events(conn, user_id, (consent_event,))
            _append_audit(conn, self._cipher, consent_event)
            return MemoryWriteResult(WriteOutcome.DONE, after, changed=True, invalidated_proposals=invalidated)

    def prepare(self, proposal: MemoryProposal) -> MemoryWriteResult:
        with _account_transaction(self._db) as conn:
            state = _memory_state(conn, self._cipher, proposal.user_id)
            outcome = decide_preparation(writable=_account_exists(conn, proposal.user_id), state=state, proposal=proposal)
            if outcome is WriteOutcome.DONE:
                if proposal.state is not ProposalState.PENDING or conn.execute(
                    "SELECT 1 FROM memory_proposals WHERE proposal_id = ?", (proposal.proposal_id,)
                ).fetchone():
                    raise IdCollision("generated identifier collision")
                _put_memory_proposal(conn, self._cipher, proposal, insert=True)
            return MemoryWriteResult(outcome, state)

    def confirm(
        self, user_id: str, proposal_id: str | None, declarations: Sequence[Declaration], expected_version: int,
        now: datetime, event: AuditDraft,
    ) -> MemoryWriteResult:
        check_confirmation(user_id, declarations, expected_version, event)
        with _account_transaction(self._db) as conn:
            state = _memory_state(conn, self._cipher, user_id)
            proposal = _memory_proposal(conn, self._cipher, user_id, proposal_id) if proposal_id is not None else None
            row = conn.execute(
                "SELECT chain_id, MAX(version) FROM user_memory WHERE user_id = ? AND type = ? GROUP BY chain_id",
                (user_id, declarations[0].type.value),
            ).fetchone()
            chain_id, head = (row[0], row[1]) if row else (None, 0)
            outcome = decide_confirmation(
                user_id=user_id, writable=_account_exists(conn, user_id), state=state, proposal_id=proposal_id, proposal=proposal,
                chain_id=chain_id, head_version=head, batch_chain_id=declarations[0].chain_id, expected_version=expected_version, now=now,
            )
            if outcome is not WriteOutcome.DONE:
                return MemoryWriteResult(outcome, state)
            if proposal is not None:
                _put_memory_proposal(conn, self._cipher, replace(proposal, state=ProposalState.CONSUMED), insert=False)
            if not _append_memory(conn, self._cipher, declarations, expected_version):
                raise RuntimeError("memory chain changed during its confirmation")
            after = with_memory_change(state)
            _put_memory_state(conn, self._cipher, after)
            confirmed = confirmation_event(event, proposal_id, declarations, expected_version, after)
            _check_memory_events(conn, user_id, (confirmed,))
            _append_audit(conn, self._cipher, confirmed)
            return MemoryWriteResult(WriteOutcome.DONE, after)

    def delete_chain(self, user_id: str, chain_id: str, event: AuditDraft) -> MemoryWriteResult:
        with _account_transaction(self._db) as conn:
            state = _memory_state(conn, self._cipher, user_id)
            if not _account_exists(conn, user_id):
                return MemoryWriteResult(WriteOutcome.NOT_WRITABLE, state)
            deleted = conn.execute("DELETE FROM user_memory WHERE user_id = ? AND chain_id = ?", (user_id, chain_id)).rowcount
            if not deleted:
                return MemoryWriteResult(WriteOutcome.NOT_FOUND, state)
            invalidated = _invalidate_memory_proposals(conn, self._cipher, user_id)
            after = with_memory_change(state)
            _put_memory_state(conn, self._cipher, after)
            detail = deletion_detail(chain_id=chain_id, deleted_versions=deleted, invalidated_proposals=invalidated, revision=after.memory_revision)
            deletion = replace(event, detail=detail)
            _check_memory_events(conn, user_id, (deletion,))
            _append_audit(conn, self._cipher, deletion)
            return MemoryWriteResult(WriteOutcome.DONE, after, deleted_versions=deleted, invalidated_proposals=invalidated)


def _import_token(conn: sqlite3.Connection, user_id: str) -> str:
    """StatementImportWrites.token over the sealed rows themselves: a rewrite seals with a fresh nonce, so any change of
    a statement, a transaction's content, a declaration or the memory state changes it, and nothing is opened."""
    digest = hashlib.sha256()
    for sql in _IMPORT_TOKEN_SQL:
        for row in conn.execute(sql, (user_id,)):
            digest.update(repr(row).encode())
        digest.update(b"|")
    return digest.hexdigest()


_IMPORT_TOKEN_SQL = (
    "SELECT statement_id, payload FROM statements WHERE user_id = ? ORDER BY statement_id",
    "SELECT txn_id, payload FROM transactions WHERE user_id = ? ORDER BY txn_id",
    "SELECT memory_id, payload FROM user_memory WHERE user_id = ? ORDER BY memory_id",
    "SELECT payload FROM memory_state WHERE user_id = ?",
)


class SqliteStatementImportWrites:
    """StatementImportWrites in one SQLite transaction; raw connection only (db.lock is already held). With accounts,
    the owner's account row is read in that transaction, before the token: an erasure commits either before it (the
    import ends OWNER_GONE) or after the import's whole commit (and erases it)."""

    def __init__(self, db: SqliteDatabase, cipher: FieldCipher, *, accounts: bool = False, personas: frozenset[str] = frozenset()) -> None:
        self._db = db
        self._cipher = cipher
        self._accounts = accounts
        self._personas = personas  # the shared demo personas this server enables: they import without an account

    def token(self, user_id: str) -> str:
        with self._db.lock:
            return _import_token(self._db.connection, user_id)

    def commit(
        self, user_id: str, token: str, statements: Sequence[StoredStatement], transactions: Sequence[PostedTransaction],
        events: Sequence[AuditDraft],
    ) -> ImportCommit:
        check_import_batch(user_id, statements, transactions, events)
        with _account_transaction(self._db) as conn:
            if self._accounts and user_id not in self._personas and not _account_exists(conn, user_id):
                return ImportCommit.OWNER_GONE
            if _import_token(conn, user_id) != token:
                return ImportCommit.CHANGED
            SqliteAccountWrites._check_events(conn, events)
            for stored in statements:
                payload = self._cipher.seal(json.dumps(to_primitive(stored)), _statement_aad(user_id, stored.statement_id))
                try:
                    conn.execute("INSERT INTO statements (statement_id, user_id, payload) VALUES (?, ?, ?)", (stored.statement_id, user_id, payload))
                except sqlite3.IntegrityError as error:
                    raise IdCollision("generated identifier collision") from error
            for p in transactions:
                payload = self._cipher.seal(json.dumps(to_primitive(p)), _transaction_aad(user_id, p.transaction.txn_id))
                try:
                    conn.execute(
                        "INSERT INTO transactions (txn_id, user_id, posted_on, payload) VALUES (?, ?, ?, ?)",
                        (p.transaction.txn_id, user_id, p.transaction.date.isoformat(), payload),
                    )
                except sqlite3.IntegrityError as error:
                    raise IdCollision("generated identifier collision") from error
            for event in events:
                _append_audit(conn, self._cipher, event)
            return ImportCommit.COMMITTED


# Literal statements per table that holds a user's rows (no SQL built from strings, ASVS V1). Whoever adds a table
# with a user_id must add it here: tests/security/test_account_deletion.py scans every table for the deleted user.
_ERASE_SQL: dict[str, str] = {
    "statements": "DELETE FROM statements WHERE user_id = ?",
    "transactions": "DELETE FROM transactions WHERE user_id = ?",
    "receipts": "DELETE FROM receipts WHERE user_id = ?",
    "connections": "DELETE FROM connections WHERE user_id = ?",
    "connection_results": "DELETE FROM connection_results WHERE user_id = ?",
    "user_memory": "DELETE FROM user_memory WHERE user_id = ?",
    "memory_state": "DELETE FROM memory_state WHERE user_id = ?",
    "memory_proposals": "DELETE FROM memory_proposals WHERE user_id = ?",
    "savings_rules": "DELETE FROM savings_rules WHERE user_id = ?",
    "proposals": "DELETE FROM proposals WHERE user_id = ?",
    "authorizations": "DELETE FROM authorizations WHERE user_id = ?",
    "investment_links": "DELETE FROM investment_links WHERE user_id = ?",
    "investment_snapshots": "DELETE FROM investment_snapshots WHERE user_id = ?",
    "investment_documents": "DELETE FROM investment_documents WHERE user_id = ?",
}
_ERASE_ACCOUNT_SQL: dict[str, str] = {  # not for a demo persona's reset: the persona and its visitors' sessions stay
    "sessions": "DELETE FROM sessions WHERE user_id = ?",
    "user_profiles": "DELETE FROM user_profiles WHERE user_id = ?",
    "user_accounts": "DELETE FROM user_accounts WHERE user_id = ?",
}


class SqliteAccountErasure:
    """Account deletion in one SQLite transaction: rows deleted (secure_delete overwrites them), audit events of the
    user turned into tombstones, the erasure event appended; then the WAL is checkpointed and truncated, so no old
    page image of the user's rows stays in it."""

    def __init__(self, db: SqliteDatabase, cipher: FieldCipher) -> None:
        self._db = db
        self._cipher = cipher

    def erase(self, user_id: str, *, keep_account: bool, event: AuditDraft) -> ErasureReport:
        with _account_transaction(self._db) as conn:
            SqliteAccountWrites._check_events(conn, (event,))
            statements = {**_ERASE_SQL, **({} if keep_account else _ERASE_ACCOUNT_SQL)}
            counts = {table: conn.execute(sql, (user_id,)).rowcount for table, sql in statements.items()}
            rows = conn.execute("SELECT sequence, event_id, user_id, record FROM audit_events WHERE user_id = ? ORDER BY sequence", (user_id,)).fetchall()
            erased: list[int] = []
            for sequence, event_id, owner, record in rows:
                original = AuditEvent.from_record(_open_record(self._cipher, (event_id, owner, record)))
                if original.draft.kind in ERASURE_KINDS:
                    continue
                tomb = tombstone(original, event.event_id, event.timestamp)
                conn.execute(
                    "UPDATE audit_events SET user_id = NULL, session_id = ?, record = ? WHERE sequence = ?",
                    (ERASED_SESSION, self._cipher.seal(json.dumps(tomb.to_record()), _aad("audit_events", None, event_id)), sequence),
                )
                erased.append(sequence)
            _append_audit(conn, self._cipher, replace(event, detail=erasure_detail(erased, counts)))
        with self._db.lock:
            self._db.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return ErasureReport(counts, len(erased))


class SqliteAuditLog:
    """Records sealed with the data key, chain included; events() opens them and the chain is verified on plaintext."""

    def __init__(self, db: SqliteDatabase, cipher: FieldCipher) -> None:
        self._db = db
        self._cipher = cipher

    def append(self, draft: AuditDraft) -> AuditEvent:
        conn = self._db.connection
        with self._db.lock:
            conn.execute("BEGIN IMMEDIATE")
            try:
                event = _append_audit(conn, self._cipher, draft)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return event

    def events(self, session_id: str | None = None) -> tuple[AuditEvent, ...]:
        if session_id is None:
            rows = self._db.fetchall("SELECT event_id, user_id, record FROM audit_events ORDER BY sequence")
        else:
            rows = self._db.fetchall(
                "SELECT event_id, user_id, record FROM audit_events WHERE session_id = ? ORDER BY sequence", (session_id,)
            )
        return tuple(AuditEvent.from_record(_open_record(self._cipher, r)) for r in rows)
