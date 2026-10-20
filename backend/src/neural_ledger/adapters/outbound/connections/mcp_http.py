"""An MCP client over Streamable HTTP for servers the user adds (ADR-047). Standard library only (urllib).

Checked against the MCP specification 2025-06-18 (transports, lifecycle, tools):
- Every message is a JSON-RPC POST to the server's one endpoint, with Accept "application/json, text/event-stream";
  the answer is either a JSON body or an SSE stream whose `data:` lines carry JSON-RPC messages.
- initialize, then the notification notifications/initialized, then requests; the server may return an
  Mcp-Session-Id header that every later request repeats, and MCP-Protocol-Version is sent after initialize.
- tools/list is paginated by nextCursor; tools/call returns content blocks, optional structuredContent and isError.

Each list or call opens its own short session. Before every request the host is resolved and every address checked
(domain check_target): https only, public addresses only. Redirects and environment proxies are not followed, the
answer is capped at 1 MB and the timeout is 10 s. Errors carry a short code, never the server's text, and never the
token, which is sent as a Bearer header to this server only.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import urlsplit

from ....application.ports import ConnectorUnavailable, TargetRefused
from ....domain.connections.model import check_target, split_url

PROTOCOL_VERSION = "2025-06-18"
USER_AGENT = "neural-ledger/0.1"
MAX_BYTES = 1_000_000
MAX_PAGES = 5  # of tools/list

Resolver = Callable[[str, int], Sequence[str]]


def resolve(host: str, port: int) -> tuple[str, ...]:
    try:
        return tuple(sorted({str(info[4][0]) for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}))
    except (OSError, UnicodeError):
        return ()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201 - urllib's signature
        raise ConnectorUnavailable("REDIRECT")


class HttpMcpClient:
    def __init__(self, *, allow_private: bool = False, timeout_s: float = 10.0, resolver: Resolver = resolve) -> None:
        self._allow_private = allow_private
        self._timeout_s = timeout_s
        self._resolve = resolver
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def list_tools(self, url: str, token: str | None) -> Sequence[Any]:
        session = self._initialize(url, token)
        tools: list[Any] = []
        cursor: str | None = None
        for page in range(MAX_PAGES):
            result = self._request(url, token, session, page + 2, "tools/list", {"cursor": cursor} if cursor else {})
            listed = result.get("tools")
            if not isinstance(listed, list):
                raise ConnectorUnavailable("PROTOCOL")
            tools.extend(listed)
            cursor = result.get("nextCursor") if isinstance(result.get("nextCursor"), str) else None
            if not cursor:
                break
        return tools

    def call_tool(self, url: str, token: str | None, name: str) -> Any:
        session = self._initialize(url, token)
        result = self._request(url, token, session, 2, "tools/call", {"name": name, "arguments": {}})
        if result.get("isError") is True:
            raise ConnectorUnavailable("TOOL_ERROR")
        structured = result.get("structuredContent")
        if isinstance(structured, (dict, list)):
            return structured
        blocks = result.get("content")
        if not isinstance(blocks, list):
            raise ConnectorUnavailable("PROTOCOL")
        texts = [_maybe_json(b["text"]) for b in blocks if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)]
        return texts[0] if len(texts) == 1 else texts

    def _initialize(self, url: str, token: str | None) -> str | None:
        params = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": {"name": "neural-ledger", "version": "0.1"}}
        _, session = self._post(url, token, None, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": params}, expect=1)
        self._post(url, token, session, {"jsonrpc": "2.0", "method": "notifications/initialized"}, expect=None)
        return session

    def _request(self, url: str, token: str | None, session: str | None, rid: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
        result, _ = self._post(url, token, session, {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}, expect=rid)
        return result

    def _post(self, url: str, token: str | None, session: str | None, message: dict[str, Any], *, expect: int | None) -> tuple[dict[str, Any], str | None]:
        self._check(url)
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "User-Agent": USER_AGENT}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if session:
            headers["Mcp-Session-Id"] = session
        if message.get("method") != "initialize":
            headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
        request = urllib.request.Request(url, data=json.dumps(message).encode("utf-8"), headers=headers, method="POST")
        try:
            with self._opener.open(request, timeout=self._timeout_s) as response:
                body = response.read(MAX_BYTES + 1)
                kind = (response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
                new_session = response.headers.get("Mcp-Session-Id") or session
        except ConnectorUnavailable:
            raise
        except urllib.error.HTTPError as exc:
            raise ConnectorUnavailable(f"HTTP_{exc.code}") from None
        except TimeoutError:
            raise ConnectorUnavailable("TIMEOUT") from None
        except (OSError, ValueError):  # URLError, connection resets, malformed URLs
            raise ConnectorUnavailable("NETWORK") from None
        if len(body) > MAX_BYTES:
            raise ConnectorUnavailable("TOO_LARGE")
        if expect is None:
            return {}, new_session  # a notification: 202 Accepted, nothing to read
        reply = _find(_messages(body, kind), expect)
        if "error" in reply:
            raise ConnectorUnavailable("RPC_ERROR")
        result = reply.get("result")
        if not isinstance(result, dict):
            raise ConnectorUnavailable("PROTOCOL")
        return result, new_session

    def _check(self, url: str) -> None:
        ours = split_url(url)
        try:
            parts = urlsplit(url)
            host, port = parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80)
        except ValueError:
            raise TargetRefused("MALFORMED") from None
        # The address checked must be the one urllib connects to: refuse any URL the two parsers read differently.
        if ours is None or (ours[2], ours[3] or port) != (host.lower(), port):
            raise TargetRefused("MALFORMED")
        # shortcut: urllib resolves the host again when it connects, so a DNS answer that changes in between (DNS
        # rebinding) is not caught; pin the checked address in a custom connection if connectors leave the sandbox.
        block = check_target(url, self._resolve(host, port) if host else (), allow_private=self._allow_private)
        if block is not None:
            raise TargetRefused(block.value)


def _messages(body: bytes, kind: str) -> list[Any]:
    try:
        text = body.decode("utf-8")
        if kind == "text/event-stream":
            found: list[Any] = []
            data: list[str] = []
            for line in [*text.splitlines(), ""]:
                if line.startswith("data:"):
                    data.append(line[5:].lstrip())
                elif not line and data:
                    found.append(json.loads("\n".join(data)))
                    data = []
            return found
        parsed = json.loads(text)
    except (UnicodeDecodeError, ValueError):
        raise ConnectorUnavailable("PROTOCOL") from None
    return parsed if isinstance(parsed, list) else [parsed]


def _find(messages: list[Any], rid: int) -> dict[str, Any]:
    for message in messages:
        if isinstance(message, dict) and message.get("id") == rid and ("result" in message or "error" in message):
            return message
    raise ConnectorUnavailable("PROTOCOL")


def _maybe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return text
