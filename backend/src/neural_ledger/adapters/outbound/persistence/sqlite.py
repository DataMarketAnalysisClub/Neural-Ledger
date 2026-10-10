"""SQLite adapters (standard library sqlite3): durable actions and audit log, zero services.

Same ports as the in-memory adapters; tests/adapters run one contract suite against both.
Postgres would be one more adapter behind the same ports.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from ....domain.actions.terms import (
    ActionTerms,
    Authorization,
    Proposal,
    ProposalStatus,
)
from ....domain.audit.events import GENESIS_HASH, AuditDraft, AuditEvent, seal
from ....domain.shared.serialization import to_primitive

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
"""


class SqliteDatabase:
    def __init__(self, path: str | Path) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript(_SCHEMA)
        self.lock = threading.Lock()


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
        row = self._db.connection.execute("SELECT payload FROM proposals WHERE proposal_id = ?", (proposal_id,)).fetchone()
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
        row = self._db.connection.execute(
            "SELECT payload, consumed_at FROM authorizations WHERE authorization_id = ?", (authorization_id,)
        ).fetchone()
        return _authorization_from(json.loads(row[0]), row[1]) if row else None

    def consume_authorization(self, authorization_id: str, at: datetime) -> bool:
        with self._db.lock:
            cursor = self._db.connection.execute(
                "UPDATE authorizations SET consumed_at = ? WHERE authorization_id = ? AND consumed_at IS NULL",
                (at.isoformat(), authorization_id),
            )
            return cursor.rowcount == 1

    def for_session(self, session_id: str) -> tuple[tuple[Proposal, ...], tuple[Authorization, ...]]:
        proposals = self._db.connection.execute("SELECT payload FROM proposals WHERE session_id = ?", (session_id,)).fetchall()
        auths = self._db.connection.execute(
            "SELECT payload, consumed_at FROM authorizations WHERE session_id = ?", (session_id,)
        ).fetchall()
        return (
            tuple(_proposal_from(json.loads(r[0])) for r in proposals),
            tuple(_authorization_from(json.loads(r[0]), r[1]) for r in auths),
        )


class SqliteAuditLog:
    def __init__(self, db: SqliteDatabase) -> None:
        self._db = db

    def append(self, draft: AuditDraft) -> AuditEvent:
        conn = self._db.connection
        with self._db.lock:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT sequence, event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1").fetchone()
                sequence, prev = (row[0] + 1, row[1]) if row else (1, GENESIS_HASH)
                event = seal(draft, sequence, prev)
                conn.execute(
                    "INSERT INTO audit_events (sequence, event_id, session_id, prev_hash, event_hash, record) VALUES (?, ?, ?, ?, ?, ?)",
                    (sequence, draft.event_id, draft.session_id, prev, event.event_hash, json.dumps(event.to_record())),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return event

    def events(self, session_id: str | None = None) -> tuple[AuditEvent, ...]:
        if session_id is None:
            rows = self._db.connection.execute("SELECT record FROM audit_events ORDER BY sequence").fetchall()
        else:
            rows = self._db.connection.execute(
                "SELECT record FROM audit_events WHERE session_id = ? ORDER BY sequence", (session_id,)
            ).fetchall()
        return tuple(AuditEvent.from_record(json.loads(r[0])) for r in rows)
