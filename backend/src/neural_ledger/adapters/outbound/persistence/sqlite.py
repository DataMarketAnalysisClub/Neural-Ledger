"""SQLite adapters (standard library sqlite3): durable actions and audit log, zero services.

Same ports as the in-memory adapters; tests/adapters run one contract suite against both.
Postgres would be one more adapter behind the same ports.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from ....application.ports import IdCollision
from ....domain.actions.terms import (
    ActionTerms,
    ActionType,
    Authorization,
    Frequency,
    Proposal,
    ProposalStatus,
    SavingsRule,
)
from ....domain.audit.events import GENESIS_HASH, AuditDraft, AuditEvent, seal
from ....domain.finance.profile import RiskProfile
from ....domain.ledger.categorization import PostedTransaction
from ....domain.ledger.entities import AccountType, InstallmentInfo, Transaction, TransactionKind
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
from .field_cipher import PREFIX, FieldCipher, FieldCipherError, WrongDataKey

_SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
    proposal_id TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    payload     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS authorizations (
    authorization_id TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL,
    payload          TEXT NOT NULL,
    consumed_at      TEXT
);
CREATE TABLE IF NOT EXISTS audit_events (
    sequence   INTEGER PRIMARY KEY,
    event_id   TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    prev_hash  TEXT NOT NULL,
    event_hash TEXT NOT NULL,
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
    email       TEXT NOT NULL UNIQUE,
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
CREATE TABLE IF NOT EXISTS meta (
    name  TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


# Literal statements per table (no SQL built from strings, ASVS V1). Whoever adds a table to _SCHEMA must add it here too.
_RESET_SQL: dict[str, tuple[str, str]] = {
    "proposals": ("SELECT COUNT(*) FROM proposals", "DELETE FROM proposals"),
    "authorizations": ("SELECT COUNT(*) FROM authorizations", "DELETE FROM authorizations"),
    "audit_events": ("SELECT COUNT(*) FROM audit_events", "DELETE FROM audit_events"),
    "statements": ("SELECT COUNT(*) FROM statements", "DELETE FROM statements"),
    "transactions": ("SELECT COUNT(*) FROM transactions", "DELETE FROM transactions"),
    "savings_rules": ("SELECT COUNT(*) FROM savings_rules", "DELETE FROM savings_rules"),
    "user_profiles": ("SELECT COUNT(*) FROM user_profiles", "DELETE FROM user_profiles"),
    "user_accounts": ("SELECT COUNT(*) FROM user_accounts", "DELETE FROM user_accounts"),
    "sessions": ("SELECT COUNT(*) FROM sessions", "DELETE FROM sessions"),
}
# Bookkeeping, not data: a reset keeps it (the key check stays valid, since a reset does not change the key).
_KEPT_ON_RESET = frozenset({"meta"})


class SqliteDatabase:
    def __init__(self, path: str | Path) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript(_SCHEMA)
        # One connection is shared by every request thread, so every use of it, reads included,
        # goes through this lock. Unserialized reads interleave cursors across threads.
        self.lock = threading.Lock()

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


def _profile_from(payload: dict) -> UserProfile:
    return UserProfile(
        user_id=payload["user_id"],
        display_name=payload["display_name"],
        language=payload["language"],
        declared_tolerance=RiskProfile(payload["declared_tolerance"]) if payload["declared_tolerance"] is not None else None,
        questionnaire=tuple(QuestionnaireAnswer(**answer) for answer in payload["questionnaire"]),
        questionnaire_version=payload["questionnaire_version"],
    )


class SqliteUserProfileStore:
    def __init__(self, db: SqliteDatabase) -> None:
        self._db = db

    def get(self, user_id: str) -> UserProfile | None:
        row = self._db.fetchone("SELECT payload FROM user_profiles WHERE user_id = ?", (user_id,))
        return _profile_from(json.loads(row[0])) if row else None

    def put(self, profile: UserProfile) -> None:
        with self._db.lock:
            self._db.connection.execute(
                "INSERT INTO user_profiles (user_id, payload) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET payload = excluded.payload",
                (profile.user_id, json.dumps(to_primitive(profile))),
            )


def _account_from(payload: dict, sample_data: int) -> UserAccount:
    return UserAccount(
        user_id=payload["user_id"],
        email=payload["email"],
        password_hash=payload["password_hash"],
        created_at=datetime.fromisoformat(payload["created_at"]),
        sample_data=bool(sample_data),
    )


def _account_row(account: UserAccount) -> tuple[str, str, str, int]:
    payload = to_primitive(account)
    payload.pop("sample_data", None)
    return account.user_id, account.email, json.dumps(payload), int(account.sample_data)


class SqliteUserAccountStore:
    """Holds emails and password hashes: the database file stays out of the repository (var/, *.db)."""

    def __init__(self, db: SqliteDatabase) -> None:
        self._db = db

    def add(self, account: UserAccount) -> bool:
        with self._db.lock:
            cursor = self._db.connection.execute(
                "INSERT OR IGNORE INTO user_accounts (user_id, email, payload, sample_data) VALUES (?, ?, ?, ?)",
                _account_row(account),
            )
            return cursor.rowcount == 1

    def get(self, user_id: str) -> UserAccount | None:
        row = self._db.fetchone("SELECT payload, sample_data FROM user_accounts WHERE user_id = ?", (user_id,))
        return _account_from(json.loads(row[0]), row[1]) if row else None

    def by_email(self, email: str) -> UserAccount | None:
        row = self._db.fetchone("SELECT payload, sample_data FROM user_accounts WHERE email = ?", (email,))
        return _account_from(json.loads(row[0]), row[1]) if row else None

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
                    if isinstance(record[-1], str) and record[-1].startswith(PREFIX):
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
    """Rules created by the simulated sandbox bank, durable across restarts like the audit log."""

    def __init__(self, db: SqliteDatabase) -> None:
        self._db = db

    def add(self, rule: SavingsRule) -> None:
        with self._db.lock:
            self._db.connection.execute(
                "INSERT INTO savings_rules (rule_id, user_id, payload) VALUES (?, ?, ?)",
                (rule.rule_id, rule.user_id, json.dumps(to_primitive(rule))),
            )

    def count(self) -> int:
        row = self._db.fetchone("SELECT COUNT(*) FROM savings_rules")
        return row[0] if row else 0

    def for_user(self, user_id: str) -> tuple[SavingsRule, ...]:
        rows = self._db.fetchall("SELECT payload FROM savings_rules WHERE user_id = ? ORDER BY sequence", (user_id,))
        return tuple(_rule_from(json.loads(r[0])) for r in rows)


class SqliteActionRepository:
    def __init__(self, db: SqliteDatabase) -> None:
        self._db = db

    def add_proposal(self, proposal: Proposal) -> None:
        with self._db.lock:
            self._db.connection.execute(
                "INSERT INTO proposals (proposal_id, session_id, payload) VALUES (?, ?, ?)",
                (proposal.proposal_id, proposal.session_id, json.dumps(to_primitive(proposal))),
            )

    def get_proposal(self, proposal_id: str) -> Proposal | None:
        row = self._db.fetchone("SELECT payload FROM proposals WHERE proposal_id = ?", (proposal_id,))
        return _proposal_from(json.loads(row[0])) if row else None

    def update_proposal(self, proposal: Proposal) -> None:
        with self._db.lock:
            self._db.connection.execute(
                "UPDATE proposals SET payload = ? WHERE proposal_id = ?",
                (json.dumps(to_primitive(proposal)), proposal.proposal_id),
            )

    def add_authorization(self, authorization: Authorization) -> None:
        payload = to_primitive(authorization)
        payload.pop("consumed_at", None)
        with self._db.lock:
            self._db.connection.execute(
                "INSERT INTO authorizations (authorization_id, session_id, payload, consumed_at) VALUES (?, ?, ?, NULL)",
                (authorization.authorization_id, authorization.session_id, json.dumps(payload)),
            )

    def get_authorization(self, authorization_id: str) -> Authorization | None:
        row = self._db.fetchone("SELECT payload, consumed_at FROM authorizations WHERE authorization_id = ?", (authorization_id,))
        return _authorization_from(json.loads(row[0]), row[1]) if row else None

    def consume_authorization(self, authorization_id: str, at: datetime) -> bool:
        with self._db.lock:
            cursor = self._db.connection.execute(
                "UPDATE authorizations SET consumed_at = ? WHERE authorization_id = ? AND consumed_at IS NULL",
                (at.isoformat(), authorization_id),
            )
            return cursor.rowcount == 1

    def for_session(self, session_id: str) -> tuple[tuple[Proposal, ...], tuple[Authorization, ...]]:
        proposals = self._db.fetchall("SELECT payload FROM proposals WHERE session_id = ?", (session_id,))
        auths = self._db.fetchall("SELECT payload, consumed_at FROM authorizations WHERE session_id = ?", (session_id,))
        return (
            tuple(_proposal_from(json.loads(r[0])) for r in proposals),
            tuple(_authorization_from(json.loads(r[0]), r[1]) for r in auths),
        )


def _append_audit(conn: sqlite3.Connection, draft: AuditDraft) -> AuditEvent:
    row = conn.execute("SELECT sequence, event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1").fetchone()
    sequence, prev = (row[0] + 1, row[1]) if row else (1, GENESIS_HASH)
    event = seal(draft, sequence, prev)
    conn.execute(
        "INSERT INTO audit_events (sequence, event_id, session_id, prev_hash, event_hash, record) VALUES (?, ?, ?, ?, ?, ?)",
        (sequence, draft.event_id, draft.session_id, prev, event.event_hash, json.dumps(event.to_record())),
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
    def __init__(self, db: SqliteDatabase) -> None:
        self._db = db

    def register(self, account: UserAccount, profile: UserProfile, session: Session, events: Sequence[AuditDraft]) -> bool:
        if profile.user_id != account.user_id or session.user_id != account.user_id or any(
            event.user_id != account.user_id for event in events
        ):
            raise ValueError("account ownership mismatch")
        with _account_transaction(self._db) as conn:
            if conn.execute("SELECT 1 FROM user_accounts WHERE email = ?", (account.email,)).fetchone():
                return False
            if (
                conn.execute("SELECT 1 FROM user_accounts WHERE user_id = ?", (account.user_id,)).fetchone()
                or conn.execute("SELECT 1 FROM user_profiles WHERE user_id = ?", (account.user_id,)).fetchone()
            ):
                raise IdCollision("generated identifier collision")
            self._check_session_and_events(conn, session, events)
            conn.execute(
                "INSERT INTO user_accounts (user_id, email, payload, sample_data) VALUES (?, ?, ?, ?)", _account_row(account)
            )
            conn.execute(
                "INSERT INTO user_profiles (user_id, payload) VALUES (?, ?)",
                (profile.user_id, json.dumps(to_primitive(profile))),
            )
            conn.execute(
                "INSERT INTO sessions (session_ref, token_hash, user_id, payload, revoked_at) VALUES (?, ?, ?, ?, ?)",
                _session_row(session),
            )
            for event in events:
                _append_audit(conn, event)
            return True

    def open_session(self, session: Session, events: Sequence[AuditDraft]) -> None:
        with _account_transaction(self._db) as conn:
            self._check_session_and_events(conn, session, events)
            conn.execute(
                "INSERT INTO sessions (session_ref, token_hash, user_id, payload, revoked_at) VALUES (?, ?, ?, ?, ?)",
                _session_row(session),
            )
            for event in events:
                _append_audit(conn, event)

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
                _append_audit(conn, event)
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
                _append_audit(conn, event)
            return True

    def update_profile(self, expected: UserProfile, updated: UserProfile, events: Sequence[AuditDraft]) -> bool:
        if updated.user_id != expected.user_id or any(event.user_id != expected.user_id for event in events):
            raise ValueError("profile ownership mismatch")
        # Raw connection only: the store and audit-log methods take db.lock, which this transaction already holds.
        with _account_transaction(self._db) as conn:
            row = conn.execute("SELECT payload FROM user_profiles WHERE user_id = ?", (expected.user_id,)).fetchone()
            if row is None or _profile_from(json.loads(row[0])) != expected:
                return False
            self._check_events(conn, events)
            conn.execute(
                "UPDATE user_profiles SET payload = ? WHERE user_id = ?", (json.dumps(to_primitive(updated)), updated.user_id)
            )
            for event in events:
                _append_audit(conn, event)
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
                _append_audit(conn, event)
            return True


class SqliteAuditLog:
    def __init__(self, db: SqliteDatabase) -> None:
        self._db = db

    def append(self, draft: AuditDraft) -> AuditEvent:
        conn = self._db.connection
        with self._db.lock:
            conn.execute("BEGIN IMMEDIATE")
            try:
                event = _append_audit(conn, draft)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return event

    def events(self, session_id: str | None = None) -> tuple[AuditEvent, ...]:
        if session_id is None:
            rows = self._db.fetchall("SELECT record FROM audit_events ORDER BY sequence")
        else:
            rows = self._db.fetchall("SELECT record FROM audit_events WHERE session_id = ? ORDER BY sequence", (session_id,))
        return tuple(AuditEvent.from_record(json.loads(r[0])) for r in rows)
