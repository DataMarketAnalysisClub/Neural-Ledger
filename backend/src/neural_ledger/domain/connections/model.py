"""Read-only connections to outside services: MCP servers the user adds, and their bank through an aggregator (ADR-047).

What a connected service returns is evidence, never authority: its text is untrusted data, its numbers become facts
marked `external` with a warning the agent must mention, and none of it reaches the forecast or any money rule.

"Read-only" is enforced on our side, because a server can mislabel its own tools. A tool is callable only if it
declares itself read-only, is not marked destructive, has no write verb in its name and needs no arguments; the user
then enables each one. Only the user's sync calls a tool, always with empty arguments: the model never reaches a
connected server, so it can neither trigger a write nor send the user's data out in an argument.
"""

from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from ..agent.untrusted import sanitize
from ..privacy.redaction import redact_text
from ..shared.envelope import Caveat, Fact

CONNECTIONS_VERSION = "cn-0.1"
MAX_NAME = 60
MAX_URL = 500
MAX_TOOLS = 50
MAX_FACTS = 60  # per tool result; a larger answer keeps its first leaves
MAX_TEXT = 4_000  # characters of a tool result kept for the agent, after redaction

# English and Spanish verbs that change state. Matched on whole words of the tool's name, after splitting
# snake_case, kebab-case and camelCase, so "get_transfers" stays readable while "create_transfer" does not.
WRITE_VERBS = frozenset(
    {
        "add", "approve", "buy", "cancel", "create", "delete", "deposit", "edit", "execute", "insert", "invest", "move",
        "order", "patch", "pay", "post", "put", "redeem", "remove", "rescue", "sell", "send", "set", "submit", "trade",
        "transfer", "update", "upsert", "withdraw", "write",
        "actualizar", "aportar", "borrar", "cancelar", "comprar", "crear", "depositar", "editar", "eliminar", "enviar",
        "girar", "invertir", "pagar", "rescatar", "retirar", "transferir", "vender",
    }
)  # fmt: skip


class ConnectionKind(str, Enum):
    MCP = "mcp"
    BANK = "bank"


class ToolBlock(str, Enum):
    """Why a tool of a connected server can never be enabled."""

    NOT_READ_ONLY = "NOT_READ_ONLY"  # the server does not declare readOnlyHint: true
    DESTRUCTIVE = "DESTRUCTIVE"  # the server declares destructiveHint: true
    WRITE_VERB = "WRITE_VERB"  # its name says it changes something, whatever it declares
    NEEDS_ARGUMENTS = "NEEDS_ARGUMENTS"  # a sync calls tools without arguments, so a required one cannot be met


class TargetBlock(str, Enum):
    """Why a server address is refused before anything is sent to it (SSRF)."""

    MALFORMED = "MALFORMED"
    NOT_HTTPS = "NOT_HTTPS"
    CREDENTIALS_IN_URL = "CREDENTIALS_IN_URL"
    PRIVATE_ADDRESS = "PRIVATE_ADDRESS"  # loopback, private, link-local (cloud metadata), reserved or multicast
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, slots=True)
class RemoteTool:
    """A tool as the server listed it. The name and description are third-party text."""

    name: str
    description: str
    read_only_hint: bool | None
    destructive_hint: bool | None
    required_args: tuple[str, ...] = ()

    @property
    def block(self) -> ToolBlock | None:
        return tool_block(self)


@dataclass(frozen=True, slots=True)
class Connection:
    connection_id: str
    user_id: str
    kind: ConnectionKind
    name: str  # the user's label
    endpoint: str  # the MCP server URL; for a bank, the aggregator's name
    created_at: datetime
    tools: tuple[RemoteTool, ...] = ()
    enabled: tuple[str, ...] = ()  # tool names the user turned on; every one passed tool_block
    last_synced_at: datetime | None = None
    state: str | None = None  # a bank's balance and seen movement ids per account (bank.py); stored sealed


@dataclass(frozen=True, slots=True)
class ConnectionSnapshot:
    """One tool's answer at one sync, already redacted. The latest per tool is what the agent reads."""

    connection_id: str
    user_id: str
    tool: str
    fetched_at: datetime
    content: str  # JSON text: redacted, at most MAX_TEXT characters
    ok: bool = True  # False: the call failed; content holds an error code, never the server's message


def words(name: str) -> tuple[str, ...]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    return tuple(w.lower() for w in re.split(r"[^A-Za-z0-9áéíóúñ]+", spaced) if w)


def tool_block(tool: RemoteTool) -> ToolBlock | None:
    if tool.destructive_hint is True:
        return ToolBlock.DESTRUCTIVE
    if any(w in WRITE_VERBS for w in words(tool.name)):
        return ToolBlock.WRITE_VERB
    if tool.read_only_hint is not True:
        return ToolBlock.NOT_READ_ONLY
    if tool.required_args:
        return ToolBlock.NEEDS_ARGUMENTS
    return None


def parse_tools(listed: Iterable[Any]) -> tuple[RemoteTool, ...]:
    """The `tools` array of an MCP tools/list answer, defensively: anything malformed is skipped, never guessed."""
    tools: list[RemoteTool] = []
    seen: set[str] = set()
    for item in listed:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        name = sanitize(item["name"])[:80]
        if not name or name in seen:
            continue
        seen.add(name)
        notes = item.get("annotations") if isinstance(item.get("annotations"), dict) else {}
        schema = item.get("inputSchema") if isinstance(item.get("inputSchema"), dict) else {}
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        description = item.get("description") if isinstance(item.get("description"), str) else ""
        tools.append(
            RemoteTool(
                name=name,
                description=redact_text(sanitize(description)),
                read_only_hint=notes.get("readOnlyHint") if isinstance(notes.get("readOnlyHint"), bool) else None,
                destructive_hint=notes.get("destructiveHint") if isinstance(notes.get("destructiveHint"), bool) else None,
                required_args=tuple(str(r) for r in required),
            )
        )
        if len(tools) == MAX_TOOLS:
            break
    return tuple(tools)


def check_name(name: str) -> str | None:
    clean = sanitize(name).strip()
    return clean[:MAX_NAME] if clean else None


_URL = re.compile(r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://(?:(?P<userinfo>[^@/?#]*)@)?(?P<host>\[[0-9A-Fa-f:.]+\]|[^:/?#\[\]@\s]+)(?::(?P<port>[^/?#]*))?(?P<rest>[/?#]\S*)?")


def split_url(url: str) -> tuple[str, bool, str, int | None] | None:
    """(scheme, has credentials, host, port) of an http(s) URL, or None if it is not one. The host is lower-case and
    an IPv6 literal loses its brackets."""
    m = _URL.fullmatch(url.strip())
    if m is None or m["scheme"].lower() not in ("http", "https"):
        return None
    port = m["port"]
    if port is not None and not (port.isdigit() and 0 < int(port) < 65536):
        return None
    return m["scheme"].lower(), m["userinfo"] is not None, m["host"].strip("[]").lower(), int(port) if port else None


def check_target(url: str, addresses: Iterable[str], *, allow_private: bool) -> TargetBlock | None:
    """Whether a server address may be called. `addresses` are what the host resolves to, all of them.

    `allow_private` (local development only) admits http and private addresses, so a server on localhost can be tried.
    """
    parts = split_url(url) if len(url) <= MAX_URL else None
    if parts is None:
        return TargetBlock.MALFORMED
    scheme, credentials, _host, _port = parts
    if credentials:
        return TargetBlock.CREDENTIALS_IN_URL
    if scheme != "https" and not allow_private:
        return TargetBlock.NOT_HTTPS
    resolved = tuple(addresses)
    if not resolved:
        return TargetBlock.UNRESOLVED
    if allow_private:
        return None
    for address in resolved:
        try:
            ip = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError:
            return TargetBlock.UNRESOLVED
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_multicast:
            return TargetBlock.PRIVATE_ADDRESS
    return None


def redact_result(value: Any) -> Any:
    """Every string in a tool's answer, keys included, through the personal-data rules; numbers stay."""
    if isinstance(value, str):
        return redact_text(sanitize(value)) if len(value) <= MAX_TEXT else redact_text(sanitize(value[:MAX_TEXT]))
    if isinstance(value, list):
        return [redact_result(v) for v in value]
    if isinstance(value, dict):
        return {redact_text(sanitize(str(k))): redact_result(v) for k, v in value.items()}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_text(sanitize(str(value)))


def snapshot_content(result: Any) -> str:
    """What is stored for one tool answer: the redacted JSON, cut to MAX_TEXT characters."""
    text = json.dumps(redact_result(result), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "…"


_KEY_PART = re.compile(r"[^A-Za-z0-9_]+")


def _key_part(text: str) -> str:
    return _KEY_PART.sub("_", text).strip("_")[:40] or "x"


def external_facts(connection_id: str, tool: str, content: str) -> tuple[Fact, ...]:
    """The numbers of one stored answer, as facts the agent may quote.

    A number's unit is the currency its object names (`currency` or `moneda`, a three-letter code), else `external`,
    which the verifier never accepts as money. A cut answer is no longer JSON and yields no facts.
    """
    try:
        data = json.loads(content)
    except ValueError:
        return ()
    facts: list[Fact] = []

    def walk(value: Any, path: tuple[str, ...], unit: str) -> None:
        if len(facts) >= MAX_FACTS:
            return
        if isinstance(value, dict):
            code = value.get("currency", value.get("moneda"))
            own = code.upper() if isinstance(code, str) and re.fullmatch(r"[A-Za-z]{3}", code) else unit
            for k in sorted(value):
                walk(value[k], (*path, _key_part(str(k))), own)
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, (*path, str(i)), unit)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            key = ".".join(("external", _key_part(connection_id), _key_part(tool), *path)) if path else f"external.{_key_part(connection_id)}.{_key_part(tool)}"
            facts.append(Fact(key, value, unit, f"reported by connected service {connection_id}, tool {tool}; not checked"))

    walk(data, (), "external")
    return tuple(facts)


def external_warning(names: Iterable[str]) -> Caveat:
    shown = ", ".join(sorted(set(names))) or "a connected service"
    return Caveat(
        "EXTERNAL_DATA",
        f"These figures come from {shown} as that service reported them; Neural Ledger has not checked them and does not use them in the forecast.",
        ("not checked", "no verificad", "未经核实", "reported by", "según informa", "informad"),
    )
