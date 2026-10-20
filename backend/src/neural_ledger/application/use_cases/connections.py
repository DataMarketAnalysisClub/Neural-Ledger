"""Read-only connections the user adds: MCP servers of other finance apps, and their bank through an aggregator (ADR-047).

Every write here is the user's, through the app (rule 3): adding, choosing tools, syncing and disconnecting. The one
agent tool, get_connected_data, reads what the last sync stored and can call nothing. A sync lists the server's tools
again first, so a tool that stops declaring itself read-only is switched off before it could be called.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any

from ...domain.agent.untrusted import sanitize, wrap_untrusted
from ...domain.audit.events import Actor, AuditDraft, AuditKind
from ...domain.connections.bank import dump_state, load_state, statement_from_sync
from ...domain.connections.model import (
    CONNECTIONS_VERSION,
    Connection,
    ConnectionKind,
    ConnectionSnapshot,
    check_name,
    external_facts,
    external_warning,
    parse_tools,
    snapshot_content,
    split_url,
)
from ...domain.shared.envelope import Envelope
from ...domain.shared.hashing import content_id
from ...domain.shared.serialization import to_primitive
from ...domain.statements.model import BankStatement
from ..ports import AuditLog, BankFeed, Clock, ConnectionStore, ConnectorUnavailable, IdGenerator, McpClient, TargetRefused
from .statements import StatementImport, StatementUseCases

MAX_CONNECTIONS = 10  # per user
FIRST_SYNC_DAYS = 365  # how far back the first bank sync reads
RESYNC_OVERLAP_DAYS = 30  # later syncs read again from this far before the last one; movement ids drop repeats
CONSENT = "connector-1"  # the consent text's version, recorded on CONNECTION_ADDED
MODES = ("off", "fixture", "live")


@dataclass(frozen=True, slots=True)
class ToolView:
    name: str
    description: dict[str, str]
    read_only_hint: bool | None
    destructive_hint: bool | None
    blocked: str | None
    enabled: bool


@dataclass(frozen=True, slots=True)
class ConnectionView:
    connection_id: str
    kind: str
    name: str
    host: str
    created_at: str
    last_synced_at: str | None
    tools: tuple[ToolView, ...]


@dataclass(frozen=True, slots=True)
class BankInfo:
    aggregator: str
    public_key: str | None


@dataclass(frozen=True, slots=True)
class BankStart:
    aggregator: str
    public_key: str | None
    widget_token: str | None  # None: no widget (fixture), connect with any exchange token


@dataclass(frozen=True, slots=True)
class ConnectionsList:
    connections: tuple[ConnectionView, ...]
    mode: str
    bank: BankInfo


@dataclass(frozen=True, slots=True)
class ToolResult:
    tool: str
    ok: bool
    error: str | None


@dataclass(frozen=True, slots=True)
class ConnectionSync:
    connection: ConnectionView
    results: tuple[ToolResult, ...]
    statements: StatementImport | None


@dataclass(frozen=True, slots=True)
class ResultView:
    tool: str
    fetched_at: str
    ok: bool
    content: dict[str, str]


@dataclass(frozen=True, slots=True)
class ConnectedSource:
    connection_id: str
    name: dict[str, str]
    host: str
    last_synced_at: str | None
    results: tuple[ResultView, ...]


@dataclass(frozen=True, slots=True)
class ConnectedData:
    connections: tuple[ConnectedSource, ...]


class ConnectionUseCases:
    def __init__(
        self,
        store: ConnectionStore,
        mcp: McpClient,
        bank: BankFeed | None,
        statements: StatementUseCases,
        audit: AuditLog,
        clock: Clock,
        ids: IdGenerator,
        mode: str = "fixture",
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"unknown connectors mode {mode!r}")
        self._store, self._mcp, self._bank, self._statements = store, mcp, bank, statements
        self._audit, self._clock, self._ids, self._mode = audit, clock, ids, mode

    @property
    def mode(self) -> str:
        """off | fixture | live, as /health and /v1/connections report it."""
        return self._mode

    def list(self, user_id: str) -> Envelope[ConnectionsList]:
        connections = self._store.for_user(user_id)
        bank = BankInfo(self._bank.name if self._bank else "none", self._bank.public_key if self._bank else None)
        return self._success(ConnectionsList(tuple(_view(c) for c in connections), self._mode, bank))

    def add_mcp(self, user_id: str, session_id: str, name: object, url: object, token: object, consent: object) -> Envelope[ConnectionView]:
        refused = self._refuse_new(user_id, consent)
        if refused is not None:
            return refused
        label = check_name(name) if isinstance(name, str) else None
        if label is None:
            return _invalid("name", "give the connection a name")
        if not isinstance(url, str) or not url.strip():
            return _invalid("url", "the server address is required")
        if token is not None and not isinstance(token, str):
            return _invalid("token", "the token must be text")
        address, secret = url.strip(), (token or "").strip() or None
        try:
            tools = parse_tools(self._mcp.list_tools(address, secret))
        except TargetRefused as exc:
            return _invalid("url", f"the address was refused ({_code(exc)}): use an https address of a public server")
        except ConnectorUnavailable as exc:
            return Envelope.insufficient(("connection",), params_version=CONNECTIONS_VERSION, message=f"the server did not answer ({_code(exc)})")
        connection = Connection(self._ids.new("conn"), user_id, ConnectionKind.MCP, label, address, self._clock.now(), tools)
        self._store.add(connection, secret)
        readable = sum(1 for t in tools if t.block is None)
        self._record(session_id, user_id, AuditKind.CONNECTION_ADDED, "ADDED", connection, f"tools={len(tools)} readable={readable} consent={CONSENT}")
        return self._success(_view(connection))

    def bank_start(self, user_id: str) -> Envelope[BankStart]:
        if self._mode == "off" or self._bank is None:
            return _invalid("bank", "no bank aggregator is available on this server")
        try:
            token = self._bank.start()
        except ConnectorUnavailable as exc:
            return Envelope.insufficient(("connection",), params_version=CONNECTIONS_VERSION, message=f"the bank link failed ({_code(exc)})")
        start = BankStart(self._bank.name, self._bank.public_key, token)
        # The widget token is single-use and secret-like: the snapshot id must not carry it.
        return Envelope.success(
            start, params_version=CONNECTIONS_VERSION, snapshot_id=content_id("bank-start", user_id, self._clock.now()), as_of=self._clock.now().date().isoformat()
        )

    def connect_bank(self, user_id: str, session_id: str, exchange_token: object, consent: object) -> Envelope[ConnectionView]:
        refused = self._refuse_new(user_id, consent)
        if refused is not None:
            return refused
        if self._bank is None:
            return _invalid("bank", "no bank aggregator is configured on this server")
        if not isinstance(exchange_token, str) or not exchange_token.strip():
            return _invalid("exchange_token", "the widget's token is required")
        try:
            link = self._bank.exchange(exchange_token.strip())
        except ConnectorUnavailable as exc:
            return Envelope.insufficient(("connection",), params_version=CONNECTIONS_VERSION, message=f"the bank link failed ({_code(exc)})")
        connection = Connection(self._ids.new("conn"), user_id, ConnectionKind.BANK, self._bank.name.capitalize(), self._bank.name, self._clock.now())
        self._store.add(connection, link)
        self._record(session_id, user_id, AuditKind.CONNECTION_ADDED, "ADDED", connection, f"consent={CONSENT}")
        return self._success(_view(connection))

    def set_tools(self, user_id: str, session_id: str, connection_id: str, enabled: object) -> Envelope[ConnectionView]:
        connection = self._store.get(user_id, connection_id)
        if connection is None or connection.kind is not ConnectionKind.MCP:
            return _missing()
        if not isinstance(enabled, list) or not all(isinstance(n, str) for n in enabled):
            return _invalid("enabled", "enabled must be a list of tool names")
        tools = {t.name: t for t in connection.tools}
        for name in enabled:
            tool = tools.get(name)
            if tool is None:
                return _invalid("enabled", "a tool name is not one this server listed")
            if tool.block is not None:
                return _invalid("enabled", f"a tool cannot be enabled ({tool.block.value})")
        updated = replace(connection, enabled=tuple(n for n in tools if n in set(enabled)))
        self._store.update(updated)
        self._record(session_id, user_id, AuditKind.CONNECTION_UPDATED, "UPDATED", updated, f"enabled={len(updated.enabled)}")
        return self._success(_view(updated))

    def sync(self, user_id: str, session_id: str, connection_id: str) -> Envelope[ConnectionSync]:
        if self._mode == "off":
            return _invalid("connection", "connections are turned off on this server")
        connection = self._store.get(user_id, connection_id)
        if connection is None:
            return _missing()
        secret = self._store.secret(user_id, connection_id)
        if connection.kind is ConnectionKind.BANK:
            return self._sync_bank(session_id, connection, secret)
        return self._sync_mcp(session_id, connection, secret)

    def remove(self, user_id: str, session_id: str, connection_id: str) -> Envelope[ConnectionView]:
        connection = self._store.get(user_id, connection_id)
        if connection is None or not self._store.remove(user_id, connection_id):
            return _missing()
        self._record(session_id, user_id, AuditKind.CONNECTION_REMOVED, "REMOVED", connection, "secret=deleted results=deleted")
        return self._success(_view(connection))

    def connected_data(self, user_id: str) -> Envelope[ConnectedData]:
        """What the agent may read: the latest answer per enabled tool, untrusted, with its numbers as external facts."""
        sources, facts, names = [], [], []
        for connection in self._store.for_user(user_id):
            if connection.kind is not ConnectionKind.MCP:
                continue  # a bank's movements are statements and transactions, with their own tools
            results = tuple(r for r in self._store.results(user_id, connection.connection_id) if r.tool in connection.enabled)
            views = tuple(ResultView(r.tool, r.fetched_at.isoformat(), r.ok, {"untrusted_text": r.content}) for r in results)
            sources.append(ConnectedSource(connection.connection_id, wrap_untrusted(connection.name), _host(connection), _iso(connection.last_synced_at), views))
            for r in results:
                if r.ok:
                    facts.extend(external_facts(connection.connection_id, r.tool, r.content))
            if any(r.ok for r in results):
                names.append(sanitize(connection.name))
        if not sources:
            return Envelope.insufficient(("connection",), params_version=CONNECTIONS_VERSION, message="the user has not connected any service")
        return Envelope.success(
            ConnectedData(tuple(sources)),
            params_version=CONNECTIONS_VERSION,
            snapshot_id=content_id("connected", user_id, [(s.connection_id, s.last_synced_at) for s in sources]),
            as_of=self._clock.now().date().isoformat(),
            facts=tuple(facts),
            warnings=(external_warning(names),) if facts else (),
        )

    def _sync_mcp(self, session_id: str, connection: Connection, secret: str | None) -> Envelope[ConnectionSync]:
        try:
            tools = parse_tools(self._mcp.list_tools(connection.endpoint, secret))
        except TargetRefused as exc:
            return _invalid("url", f"the address was refused ({_code(exc)})")
        except ConnectorUnavailable as exc:
            return Envelope.insufficient(("connection",), params_version=CONNECTIONS_VERSION, message=f"the server did not answer ({_code(exc)})")
        callable_now = {t.name for t in tools if t.block is None}
        enabled = tuple(n for n in connection.enabled if n in callable_now)  # a tool that changed its declaration is off
        now = self._clock.now()
        results, snapshots = [], []
        for name in enabled:
            try:
                content, ok, error = snapshot_content(self._mcp.call_tool(connection.endpoint, secret, name)), True, None
            except (ConnectorUnavailable, TargetRefused) as exc:
                content, ok, error = "", False, _code(exc)
            results.append(ToolResult(name, ok, error))
            snapshots.append(ConnectionSnapshot(connection.connection_id, connection.user_id, name, now, content, ok))
        self._store.put_results(connection.user_id, connection.connection_id, snapshots)
        updated = replace(connection, tools=tools, enabled=enabled, last_synced_at=now)
        self._store.update(updated)
        failed = sorted({r.error for r in results if r.error})
        dropped = len(connection.enabled) - len(enabled)
        detail = f"called={len(results)} ok={sum(r.ok for r in results)} failed={','.join(failed) or 'none'} switched_off={dropped}"
        self._record(session_id, connection.user_id, AuditKind.CONNECTION_SYNCED, "SYNCED", updated, detail)
        return self._success(ConnectionSync(_view(updated), tuple(results), None))

    def _sync_bank(self, session_id: str, connection: Connection, link: str | None) -> Envelope[ConnectionSync]:
        if self._bank is None or link is None:
            return _invalid("bank", "no bank aggregator is configured on this server")
        states = load_state(connection.state)
        today = self._clock.now().date()
        since = min((s.synced_on for s in states.values()), default=None)
        since = today - timedelta(days=FIRST_SYNC_DAYS) if since is None else since - timedelta(days=RESYNC_OVERLAP_DAYS)
        try:
            accounts = self._bank.fetch(link, since)
        except ConnectorUnavailable as exc:
            return Envelope.insufficient(("connection",), params_version=CONNECTIONS_VERSION, message=f"the bank did not answer ({_code(exc)})")
        statements: list[BankStatement] = []
        new_states = dict(states)
        for account, movements in accounts:
            statement, state = statement_from_sync(self._bank.name, account, movements, states.get(account.account_id), today)
            new_states[account.account_id] = state
            if statement is not None:
                statements.append(statement)
        imported: Envelope[StatementImport] | None = None
        if statements:
            imported = self._statements.import_read(connection.user_id, statements, session_id)
            if not imported.ok:
                return imported  # type: ignore[return-value]  # nothing stored and the state not advanced: the next sync retries
        updated = replace(connection, last_synced_at=self._clock.now(), state=dump_state(new_states))
        self._store.update(updated)
        detail = f"accounts={len(accounts)} statements={len(statements)}"
        self._record(session_id, connection.user_id, AuditKind.CONNECTION_SYNCED, "SYNCED", updated, detail)
        return Envelope.success(
            ConnectionSync(_view(updated), (), imported.data if imported else None),
            params_version=CONNECTIONS_VERSION,
            snapshot_id=imported.snapshot_id if imported and imported.snapshot_id else content_id("connection-sync", to_primitive(updated)),
            as_of=today.isoformat(),
            facts=imported.facts if imported else (),
            warnings=imported.warnings if imported else (),
        )

    def _refuse_new(self, user_id: str, consent: object) -> Envelope[Any] | None:
        if self._mode == "off":
            return _invalid("connection", "connections are turned off on this server")
        if consent is not True:
            return _invalid("consent", "the user must agree to read this service's data")
        if len(self._store.for_user(user_id)) >= MAX_CONNECTIONS:
            return _invalid("connection", f"at most {MAX_CONNECTIONS} connections per user")
        return None

    def _success(self, data: Any) -> Envelope[Any]:
        snapshot = content_id("connection", to_primitive(data))
        return Envelope.success(data, params_version=CONNECTIONS_VERSION, snapshot_id=snapshot, as_of=self._clock.now().date().isoformat())

    def _record(self, session_id: str, user_id: str, kind: AuditKind, result: str, connection: Connection, detail: str) -> None:
        # Kind and host only: never the full address (it can carry a token in its query), a secret or any content.
        self._audit.append(
            AuditDraft(
                event_id=self._ids.new("evt"),
                timestamp=self._clock.now(),
                session_id=session_id,
                user_id=user_id,
                actor=Actor.USER,
                kind=kind,
                forecast_snapshot_id=connection.connection_id,
                policy_version=CONNECTIONS_VERSION,
                execution_result=result,
                detail=f"kind={connection.kind.value} host={_host(connection)} {detail}",
            )
        )


def _view(connection: Connection) -> ConnectionView:
    tools = tuple(
        ToolView(t.name, {"untrusted_text": t.description}, t.read_only_hint, t.destructive_hint, t.block.value if t.block else None, t.name in connection.enabled)
        for t in connection.tools
    )
    return ConnectionView(
        connection.connection_id, connection.kind.value, connection.name, _host(connection),
        connection.created_at.isoformat(), _iso(connection.last_synced_at), tools,
    )


def _host(connection: Connection) -> str:
    if connection.kind is ConnectionKind.BANK:
        return connection.endpoint
    parts = split_url(connection.endpoint)
    return parts[2] if parts else "unknown"


def _iso(moment: Any) -> str | None:
    return moment.isoformat() if moment is not None else None


def _code(exc: Exception) -> str:
    """The short code an adapter raised with; anything longer is replaced, so no server text reaches the user."""
    first = exc.args[0] if exc.args else None
    value = getattr(first, "value", first)
    return value if isinstance(value, str) and value.replace("_", "").isalnum() and len(value) <= 40 else "ERROR"


def _invalid(field: str, message: str) -> Envelope[Any]:
    return Envelope.invalid(field, (), params_version=CONNECTIONS_VERSION, message=message)


def _missing() -> Envelope[Any]:
    return Envelope.insufficient(("connection",), params_version=CONNECTIONS_VERSION, message="no such connection for this user")
