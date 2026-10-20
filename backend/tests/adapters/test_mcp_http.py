"""The MCP client against a local fake server (ADR-047): the protocol both ways, and every refusal. No network.

The fake speaks Streamable HTTP as MCP 2025-06-18 describes it: initialize returns a session id, notifications get
202, and answers come as JSON or as an SSE stream. It records what it received, so the tests can check the token
travels only as a Bearer header and the session id is repeated.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from neural_ledger.adapters.outbound.connections.mcp_http import MAX_BYTES, HttpMcpClient
from neural_ledger.application.ports import ConnectorUnavailable, McpClient, TargetRefused

TOKEN = "test_token_not_a_real_one"
TOOLS = [
    {"name": "get_portfolio", "description": "Saldo", "annotations": {"readOnlyHint": True}, "inputSchema": {"type": "object"}},
    {"name": "invest", "annotations": {"readOnlyHint": False}, "inputSchema": {"type": "object", "required": ["amount"]}},
]

Reply = Callable[[dict], tuple[int, object, dict[str, str]]]


def server_like(message: dict) -> tuple[int, object, dict[str, str]]:
    method = message.get("method")
    if method == "initialize":
        return 200, {"jsonrpc": "2.0", "id": message["id"], "result": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}}}, {"Mcp-Session-Id": "sess-1"}
    if method == "notifications/initialized":
        return 202, b"", {}
    if method == "tools/list":
        page = message["params"].get("cursor")
        tools, cursor = (TOOLS[1:], None) if page == "p2" else (TOOLS[:1], "p2")
        return 200, {"jsonrpc": "2.0", "id": message["id"], "result": {"tools": tools, **({"nextCursor": cursor} if cursor else {})}}, {}
    if method == "tools/call":
        result = {"content": [{"type": "text", "text": json.dumps({"balance": 1_000, "currency": "CLP"})}]}
        return 200, {"jsonrpc": "2.0", "id": message["id"], "result": result}, {}
    return 200, {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32601, "message": "secret detail from the server"}}, {}


class FakeMcp:
    def __init__(self, reply: Reply = server_like, *, sse: bool = False) -> None:
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 (http.server API)
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                outer.requests.append({"headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                status, payload, headers = reply(body)
                if isinstance(payload, bytes):
                    data, kind = payload, "application/json"
                elif sse:
                    data, kind = f"event: message\ndata: {json.dumps(payload)}\n\n".encode(), "text/event-stream"
                else:
                    data, kind = json.dumps(payload).encode(), "application/json"
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(data)))
                for k, v in headers.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_):  # keep test output quiet
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}/mcp"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def fake():
    server = FakeMcp()
    yield server
    server.close()


def local() -> HttpMcpClient:
    return HttpMcpClient(allow_private=True, timeout_s=5)


def test_it_is_an_mcp_client():
    assert isinstance(local(), McpClient)


def test_lists_every_page_with_the_session_and_the_token(fake):
    tools = local().list_tools(fake.url, TOKEN)
    assert [t["name"] for t in tools] == ["get_portfolio", "invest"]
    methods = [r["body"].get("method") for r in fake.requests]
    assert methods == ["initialize", "notifications/initialized", "tools/list", "tools/list"]
    later = fake.requests[1:]
    assert all(r["headers"]["mcp-session-id"] == "sess-1" for r in later)
    assert all(r["headers"]["mcp-protocol-version"] == "2025-06-18" for r in later)
    assert all(r["headers"]["authorization"] == f"Bearer {TOKEN}" for r in fake.requests)


def test_calls_a_tool_with_empty_arguments_and_parses_its_json_text(fake):
    assert local().call_tool(fake.url, None, "get_portfolio") == {"balance": 1_000, "currency": "CLP"}
    call = fake.requests[-1]["body"]
    assert call["params"] == {"name": "get_portfolio", "arguments": {}}
    assert "authorization" not in fake.requests[-1]["headers"]  # no token, no header


def test_reads_an_sse_answer():
    server = FakeMcp(sse=True)
    try:
        assert [t["name"] for t in local().list_tools(server.url, None)] == ["get_portfolio", "invest"]
    finally:
        server.close()


@pytest.mark.parametrize(
    ("reply", "code"),
    [
        (lambda m: (500, {"error": "boom"}, {}), "HTTP_500"),
        (lambda m: (200, b"not json", {}) if m.get("method") == "initialize" else server_like(m), "PROTOCOL"),
        (lambda m: server_like(m) if m.get("method") != "tools/call" else (200, {"jsonrpc": "2.0", "id": m["id"], "result": {"isError": True, "content": []}}, {}), "TOOL_ERROR"),
        (lambda m: server_like(m) if m.get("method") != "tools/call" else server_like({"method": "unknown", "id": m["id"]}), "RPC_ERROR"),
        (lambda m: (302, b"", {"Location": "http://169.254.169.254/latest/meta-data"}), "REDIRECT"),
        (lambda m: (200, b"[" + b"1," * MAX_BYTES + b"1]", {}), "TOO_LARGE"),
    ],
)
def test_errors_are_short_codes_without_the_servers_text(reply, code):
    server = FakeMcp(reply)
    try:
        with pytest.raises(ConnectorUnavailable) as raised:
            local().call_tool(server.url, TOKEN, "get_portfolio")
        assert raised.value.args == (code,)
        assert "secret detail" not in str(raised.value) and TOKEN not in str(raised.value)
    finally:
        server.close()


def test_a_redirect_is_never_followed():
    server = FakeMcp(lambda m: (302, b"", {"Location": "http://169.254.169.254/"}))
    try:
        with pytest.raises(ConnectorUnavailable):
            local().list_tools(server.url, None)
        assert len(server.requests) == 1
    finally:
        server.close()


def test_a_private_address_is_refused_before_any_request(fake):
    strict = HttpMcpClient(timeout_s=5)  # production: https and public addresses only
    with pytest.raises(TargetRefused) as raised:
        strict.list_tools(fake.url, TOKEN)
    assert raised.value.args == ("NOT_HTTPS",)
    with pytest.raises(TargetRefused) as raised:
        strict.list_tools(fake.url.replace("http://", "https://"), TOKEN)
    assert raised.value.args == ("PRIVATE_ADDRESS",)
    assert fake.requests == []


def test_a_name_that_resolves_to_a_private_address_is_refused():
    rebinding = HttpMcpClient(resolver=lambda host, port: ("93.184.216.34", "10.0.0.7"))
    with pytest.raises(TargetRefused) as raised:
        rebinding.list_tools("https://mcp.example.com/mcp", None)
    assert raised.value.args == ("PRIVATE_ADDRESS",)


@pytest.mark.parametrize(
    "url",
    [
        "https://mcp.example.com\\@10.0.0.7/mcp",  # parsers that disagree on the host
        "https://user:pw@mcp.example.com/mcp",
        "https://mcp.example.com:99999/mcp",
        "file:///etc/passwd",
    ],
)
def test_ambiguous_or_foreign_urls_are_refused(url):
    client = HttpMcpClient(resolver=lambda host, port: ("93.184.216.34",))
    with pytest.raises(TargetRefused):
        client.list_tools(url, None)
