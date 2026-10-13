"""The OpenRouter adapter against a local fake OpenAI-compatible server: no network, no key."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from neural_ledger.adapters.outbound.llm.openrouter import OpenRouterLanguageModel
from neural_ledger.adapters.outbound.llm.scripted import ScriptedLanguageModel
from neural_ledger.application.conversation import (
    AssistantEntry,
    ModelRequest,
    ToolCall,
    ToolResultEntry,
    ToolSpec,
    TurnContext,
    UserEntry,
)
from neural_ledger.application.ports import LanguageModelUnavailable
from neural_ledger.application.services.llm_fallback import FallbackLanguageModel
from neural_ledger.bootstrap.container import build
from tests.conftest import make_settings

CONTEXT = TurnContext("affordability", 0.95, "proceed", "T1", "2026-10-29", "CLP")
SPEC = ToolSpec("simulate_purchase", "Simulate a purchase.", {"type": "object", "properties": {"amount": {"type": "integer"}}}, "T1")
SECRET = "test_secret_value_not_a_real_key"
MODEL = "vendor/some-model"

ADAPTERS = {"openrouter": OpenRouterLanguageModel}


class FakeServer:
    """Serves one canned reply per request and records what it received."""

    def __init__(self, status: int = 200, body: object = None, raw: bytes | None = None) -> None:
        self.status, self.body, self.raw = status, body, raw
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 (http.server API)
                length = int(self.headers.get("Content-Length", 0))
                outer.requests.append(
                    {"path": self.path, "headers": dict(self.headers), "body": json.loads(self.rfile.read(length) or b"{}")}
                )
                payload = outer.raw if outer.raw is not None else json.dumps(outer.body).encode()
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):  # keep test output clean
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_port}/api/v1"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def serve():
    servers: list[FakeServer] = []

    def start(**kwargs) -> FakeServer:
        server = FakeServer(**kwargs)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.close()


@pytest.fixture(params=sorted(ADAPTERS))
def provider(request) -> str:
    return request.param


def reply(content: str | None = None, tool_calls: list | None = None) -> dict:
    message: dict = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {"choices": [{"index": 0, "message": message, "finish_reason": "stop"}]}


def call(call_id: str, name: str, arguments: object) -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


def request(*entries, tools=(SPEC,)) -> ModelRequest:
    return ModelRequest("SYSTEM PROMPT", tuple(entries), tuple(tools), CONTEXT)


def adapter(provider: str, server: FakeServer, **kwargs):
    return ADAPTERS[provider](SECRET, MODEL, base_url=server.url, timeout_s=5, **kwargs)


# ---- behaviour shared by every OpenAI-compatible provider -------------------------------------


def test_text_reply(provider, serve):
    server = serve(body=reply("Your balance is fine."))
    turn = adapter(provider, server).respond(request(UserEntry("hi")))
    assert turn.text == "Your balance is fine." and turn.tool_calls == () and turn.model_version == f"{provider}:{MODEL}"


def test_request_shape_and_auth(provider, serve):
    server = serve(body=reply("ok"))
    adapter(provider, server).respond(request(UserEntry("hi")))
    sent = server.requests[0]
    assert sent["path"] == "/api/v1/chat/completions"
    assert sent["headers"]["Authorization"] == f"Bearer {SECRET}"
    assert sent["headers"]["User-Agent"].startswith("neural-ledger")
    body = sent["body"]
    assert body["model"] == MODEL
    assert body["messages"][0] == {"role": "system", "content": "SYSTEM PROMPT"}
    assert body["messages"][1] == {"role": "user", "content": "hi"}
    assert body["tools"] == [
        {"type": "function", "function": {"name": "simulate_purchase", "description": "Simulate a purchase.", "parameters": SPEC.input_schema}}
    ]


def test_no_tools_key_when_the_turn_allows_none(provider, serve):
    server = serve(body=reply("ok"))
    adapter(provider, server).respond(request(UserEntry("hi"), tools=()))
    assert "tools" not in server.requests[0]["body"]


def test_tool_call_arguments_are_parsed_from_a_json_string(provider, serve):
    server = serve(body=reply(None, [call("c1", "simulate_purchase", '{"amount": 400000, "installments": 12}')]))
    turn = adapter(provider, server).respond(request(UserEntry("laptop?")))
    assert turn.text is None
    assert turn.tool_calls == (ToolCall("c1", "simulate_purchase", {"amount": 400000, "installments": 12}),)


@pytest.mark.parametrize("arguments", ["not json", "[1, 2]", '"text"', "", None, 7])
def test_unusable_arguments_become_an_empty_object(provider, serve, arguments):
    server = serve(body=reply(None, [call("c1", "simulate_purchase", arguments)]))
    turn = adapter(provider, server).respond(request(UserEntry("x")))
    assert turn.tool_calls[0].arguments == {}


def test_text_is_dropped_when_the_model_also_calls_tools(provider, serve):
    server = serve(body=reply("Let me check.", [call("c1", "simulate_purchase", "{}")]))
    turn = adapter(provider, server).respond(request(UserEntry("x")))
    assert turn.text is None and len(turn.tool_calls) == 1


def test_history_is_mapped_with_tool_results(provider, serve):
    server = serve(body=reply("done"))
    entries = (
        UserEntry("laptop?"),
        AssistantEntry(None, (ToolCall("c1", "simulate_purchase", {"amount": 400000}),)),
        ToolResultEntry("c1", "simulate_purchase", {"status": "OK"}),
    )
    adapter(provider, server).respond(request(*entries))
    messages = server.requests[0]["body"]["messages"]
    assert messages[2] == {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "simulate_purchase", "arguments": '{"amount": 400000}'}}],
    }
    assert messages[3] == {"role": "tool", "tool_call_id": "c1", "content": '{"status": "OK"}'}


def test_orphan_tool_exchange_at_the_start_of_history_is_trimmed(provider, serve):
    server = serve(body=reply("ok"))
    entries = (
        AssistantEntry(None, (ToolCall("c0", "simulate_purchase", {}),)),
        ToolResultEntry("c0", "simulate_purchase", {"status": "OK"}),
        UserEntry("and now?"),
    )
    adapter(provider, server).respond(request(*entries))
    roles = [m["role"] for m in server.requests[0]["body"]["messages"]]
    assert roles == ["system", "user"]


@pytest.mark.parametrize("status", [400, 401, 402, 413, 429, 500, 502, 503])
def test_http_errors_raise_unavailable_without_leaking_the_key(provider, serve, status):
    server = serve(status=status, body={"error": {"message": "nope"}})
    with pytest.raises(LanguageModelUnavailable) as caught:
        adapter(provider, server).respond(request(UserEntry("hi")))
    assert SECRET not in str(caught.value) and f"HTTP {status}" in str(caught.value)


def test_the_provider_error_message_is_reported_to_diagnose_a_fallback(provider, serve):
    server = serve(status=400, body={"error": {"message": "tool_use_failed", "code": "tool_use_failed"}})
    with pytest.raises(LanguageModelUnavailable, match="HTTP 400.*tool_use_failed"):
        adapter(provider, server).respond(request(UserEntry("hi")))


def test_a_fallback_is_logged_with_its_reason(provider, serve, caplog):
    server = serve(status=401, body={"error": {"message": "invalid api key"}})
    chain = FallbackLanguageModel([adapter(provider, server), ScriptedLanguageModel()])
    with caplog.at_level("WARNING"):
        turn = chain.respond(request(UserEntry("Will I be OK in December?")))
    assert turn.model_version == "scripted-0.1"
    assert f"{provider}:{MODEL} unavailable" in caplog.text and "HTTP 401" in caplog.text
    assert SECRET not in caplog.text


@pytest.mark.parametrize("body", [{}, {"choices": []}, {"choices": [{}]}, {"choices": [None]}, {"choices": [{"message": {"tool_calls": [{"id": "c"}]}}]}])
def test_malformed_responses_raise_unavailable(provider, serve, body):
    server = serve(body=body)
    with pytest.raises(LanguageModelUnavailable):
        adapter(provider, server).respond(request(UserEntry("hi")))


def test_an_empty_reply_is_logged_with_its_finish_reason(provider, serve, caplog):
    server = serve(body={"choices": [{"message": {"role": "assistant", "content": ""}, "finish_reason": "length"}]})
    with caplog.at_level("WARNING"):
        turn = adapter(provider, server).respond(request(UserEntry("hi")))
    assert turn.text is None and turn.tool_calls == ()
    assert "empty reply (finish_reason=length)" in caplog.text


def test_an_error_reported_inside_an_http_200_raises_unavailable(provider, serve):
    server = serve(status=200, body={"error": {"code": 502, "message": "upstream model is down"}})
    with pytest.raises(LanguageModelUnavailable, match="upstream model is down"):
        adapter(provider, server).respond(request(UserEntry("hi")))


def test_non_json_body_raises_unavailable(provider, serve):
    server = serve(raw=b"<html>gateway error</html>")
    with pytest.raises(LanguageModelUnavailable):
        adapter(provider, server).respond(request(UserEntry("hi")))


def test_unreachable_server_raises_unavailable(provider, serve):
    server = serve(body=reply("ok"))
    unreachable = adapter(provider, server)
    server.close()
    with pytest.raises(LanguageModelUnavailable):
        unreachable.respond(request(UserEntry("hi")))


def test_an_api_key_is_required(provider):
    with pytest.raises(ValueError, match=f"{provider.upper()}_API_KEY"):
        ADAPTERS[provider]("", MODEL)


# ---- provider-specific request fields ---------------------------------------------------------


def test_openrouter_only_routes_to_providers_that_support_every_parameter(serve):
    server = serve(body=reply("ok"))
    adapter("openrouter", server).respond(request(UserEntry("hi")))
    assert server.requests[0]["body"]["provider"] == {"require_parameters": True}


def test_openrouter_sends_no_temperature_unless_asked(serve):
    # Claude 5.x endpoints reject `temperature`; sending it with require_parameters leaves no endpoint to route to.
    server = serve(body=reply("ok"))
    adapter("openrouter", server).respond(request(UserEntry("hi")))
    adapter("openrouter", server, temperature=0.2).respond(request(UserEntry("hi")))
    assert "temperature" not in server.requests[0]["body"]
    assert server.requests[1]["body"]["temperature"] == 0.2


# ---- wiring -----------------------------------------------------------------------------------


def test_container_wires_openrouter_with_a_scripted_fallback():
    services, _ = build(make_settings(llm="openrouter", openrouter_api_key=SECRET))
    assert services.mode == "live"
    assert services.language_model.startswith("openrouter:anthropic/claude-haiku-5.5+scripted")


def test_container_honors_an_explicit_model_name():
    services, _ = build(make_settings(llm="openrouter", openrouter_api_key=SECRET, llm_model="openai/gpt-oss-120b"))
    assert services.language_model.startswith("openrouter:openai/gpt-oss-120b+scripted")


def test_a_missing_key_fails_loudly_at_startup():
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        build(make_settings(llm="openrouter"))
