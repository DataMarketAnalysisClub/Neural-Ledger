"""The Jev adapter against a local fake System One server: no network, no key."""

from __future__ import annotations

import pytest

from neural_ledger.adapters.outbound.decision.jev import JevDecisionModel
from neural_ledger.adapters.outbound.decision.rules import RulesDecisionModel
from neural_ledger.application.ports import DecisionModelUnavailable
from neural_ledger.application.services.decisions import DecisionService
from neural_ledger.bootstrap.container import _jev
from neural_ledger.domain.agent.policy import AP_0_1, Gate
from neural_ledger.domain.agent.questions import (
    INJECTION_QUESTION,
    INTENT_QUESTION,
    TOLERANCE_QUESTION,
    ChoiceQuestion,
    Intent,
)
from tests.adapters.test_openai_compatible_adapters import FakeServer
from tests.conftest import make_settings

SECRET = "test_secret_value_not_a_real_key"


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


def jev(server: FakeServer, **kwargs) -> JevDecisionModel:
    return JevDecisionModel(SECRET, base_url=server.url, **kwargs)


def probabilities(winner: str, p: float = 0.9) -> dict[str, float]:
    options = INTENT_QUESTION.options
    rest = round((1 - p) / (len(options) - 1), 6)
    return {o: p if o == winner else rest for o in options}


def answer(model: str = "jev-1.13.0", intent: str = "forecast", p: float = 0.9, injection: float = 0.02) -> dict:
    return {
        "model": model,
        "answers": {
            "intent": {"type": "choice", "choice": intent, "probabilities": probabilities(intent, p), "confidence": 0.81},
            "injection": {"type": "noul", "noul": injection},
        },
        "usage": {"input_tokens": 300, "output_tokens": 30},
    }


def test_request_shape_and_auth(serve):
    server = serve(body=answer())
    jev(server).judge("Will I be OK in December?", (INTENT_QUESTION, INJECTION_QUESTION))
    (sent,) = server.requests
    assert sent["path"].endswith("/v1/systemone") and sent["headers"]["Authorization"] == f"Bearer {SECRET}"
    body = sent["body"]
    assert body["state"] == "Will I be OK in December?" and body["model"] == "jev-latest"
    assert body["questions"]["injection"] == {"type": "noul", "instructions": INJECTION_QUESTION.prompt}
    intent = body["questions"]["intent"]
    assert intent["type"] == "choice" and list(intent["criteria"]) == list(INTENT_QUESTION.options)
    assert intent["criteria"]["forecast"] == INTENT_QUESTION.notes[1]


def test_options_without_notes_send_null_criteria(serve):
    server = serve(body={"model": "jev-1.13.0", "answers": {"pick": {"type": "choice", "choice": "a", "probabilities": {"a": 0.7, "b": 0.3}, "confidence": 0.6}}})
    jev(server).judge("x", (ChoiceQuestion("pick", "Pick one", ("a", "b")),))
    assert server.requests[0]["body"]["questions"]["pick"]["criteria"] == {"a": None, "b": None}


def test_answers_become_judgments_and_report_the_versioned_model(serve):
    server = serve(body=answer(model="jev-1.13.0", intent="savings_plan", p=0.7, injection=0.9))
    result = jev(server).judge("x", (INTENT_QUESTION, INJECTION_QUESTION))
    intent, injection = result["intent"], result["injection"]
    assert intent.label == "savings_plan" and intent.confidence == 0.81 and intent.source == "jev:jev-1.13.0"
    assert intent.probability("savings_plan") == 0.7 and set(dict(intent.probabilities)) == set(INTENT_QUESTION.options)
    assert injection.label == "yes" and injection.probability("yes") == 0.9 and injection.confidence == 0.9


def test_a_score_answer_picks_the_most_probable_level(serve):
    body = {
        "model": "jev-1.13.0",
        "answers": {"risk_tolerance": {"type": "score", "score": 1.05, "legend": {}, "probabilities": {"0": 0.0, "1": 0.95, "2": 0.05}, "confidence": 0.92}},
    }
    result = jev(serve(body=body)).judge("x", (TOLERANCE_QUESTION,))
    judgment = result["risk_tolerance"]
    assert judgment.label == "moderate" and judgment.confidence == 0.92 and judgment.probability("aggressive") == 0.05


def test_no_key_means_no_request(serve):
    server = serve(body=answer())
    with pytest.raises(DecisionModelUnavailable, match="no API key"):
        JevDecisionModel(None, base_url=server.url).judge("x", (INTENT_QUESTION,))
    assert server.requests == []


@pytest.mark.parametrize("status", [401, 422, 429, 500, 529])
def test_http_errors_raise_unavailable_without_leaking_the_key(serve, status):
    server = serve(status=status, body={"error": "nope"})
    with pytest.raises(DecisionModelUnavailable) as caught:
        jev(server).judge("x", (INTENT_QUESTION,))
    assert SECRET not in str(caught.value) and f"HTTP {status}" in str(caught.value)


def test_a_dead_server_raises_unavailable():
    with pytest.raises(DecisionModelUnavailable, match="request failed"):
        JevDecisionModel(SECRET, base_url="http://127.0.0.1:9", timeout_s=1.0).judge("x", (INTENT_QUESTION,))


def broken(**changes) -> dict:
    body = answer()
    body["answers"]["intent"].update(changes)
    return body


@pytest.mark.parametrize(
    "body",
    [
        broken(choice="invent_money"),
        broken(confidence=1.5),
        broken(confidence=True),
        broken(type="noul"),
        {"model": "jev-1.13.0", "answers": {"intent": answer()["answers"]["intent"]}},  # injection missing
        {"model": "jev-1.13.0"},
        ["not", "an", "object"],
    ],
)
def test_malformed_answers_raise_unavailable(serve, body):
    with pytest.raises(DecisionModelUnavailable, match="unexpected response"):
        jev(serve(body=body)).judge("x", (INTENT_QUESTION, INJECTION_QUESTION))


def test_non_json_raises_unavailable(serve):
    with pytest.raises(DecisionModelUnavailable, match="request failed"):
        jev(serve(raw=b"<html>gateway</html>")).judge("x", (INTENT_QUESTION,))


def test_the_chain_uses_jev_then_falls_through_to_rules_when_it_is_down(serve):
    up = DecisionService([jev(serve(body=answer(intent="forecast", p=0.95))), RulesDecisionModel()], AP_0_1)
    result = up.classify("zzz")
    assert result.answered_by == "jev:jev-latest" and result.intent is Intent.FORECAST and result.gate is Gate.PROCEED
    down = DecisionService([jev(serve(status=529, body={})), RulesDecisionModel()], AP_0_1)
    fallback = down.classify("Will I be OK in December?")
    assert fallback.answered_by == "rules-0.1" and fallback.intent is Intent.FORECAST


def test_the_container_sends_jev_through_openrouter_unless_only_a_typesafe_key_exists():
    via_openrouter = _jev(make_settings(openrouter_api_key="or-key", typesafe_api_key="ts-key"))
    assert via_openrouter.endpoint == "https://openrouter.ai/api/v1/systemone"
    direct = _jev(make_settings(typesafe_api_key="ts-key"))
    assert direct.endpoint == "https://api.typesafe.ai/v1/systemone"
    assert _jev(make_settings()).endpoint == "https://openrouter.ai/api/v1/systemone"  # no key: unavailable, rules answer
