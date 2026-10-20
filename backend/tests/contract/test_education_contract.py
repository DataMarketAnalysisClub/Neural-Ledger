"""search_financial_concepts (ADR-040): its input contract, its output contract and its tier."""

from __future__ import annotations

import json

import pytest

from neural_ledger.application.conversation import ToolCall
from neural_ledger.application.services.tools import ToolContext
from neural_ledger.domain.permissions.policy import Tier
from neural_ledger.domain.shared.serialization import to_primitive
from tests.education_fakes import FakeKnowledgeBase, education, registry_with

from ..conftest import CONTRACTS
from .test_contracts import validate

jsonschema = pytest.importorskip("jsonschema")
INPUT = json.loads((CONTRACTS / "tools/search_financial_concepts.input.schema.json").read_text(encoding="utf-8"))


def test_the_tool_is_t0_in_code_and_contract(services):
    assert INPUT["x-tier"] == "T0" and services.registry.tier_of("search_financial_concepts").value == "T0"


@pytest.mark.parametrize(
    "args, ok",
    [
        ({"query": "¿Qué es un ETF?"}, True),
        ({"query": "What is an ETF?", "lang": "en", "k": 5}, True),
        ({}, False),
        ({"query": ""}, False),
        ({"query": "x" * 301}, False),
        ({"query": "etf", "lang": "fr"}, False),
        ({"query": "etf", "k": 0}, False),
        ({"query": "etf", "k": 6}, False),
        ({"query": "etf", "amount": 1000}, False),
    ],
)
def test_input_contract(args, ok):
    assert jsonschema.Draft202012Validator(INPUT).is_valid(args) is ok


@pytest.mark.parametrize("kb", [FakeKnowledgeBase(), FakeKnowledgeBase(cards=()), FakeKnowledgeBase(unavailable=True)])
def test_outputs_match_the_envelope_and_the_output_contract(kb):
    payload = to_primitive(education(kb).explain("camila", "¿Qué es un ETF?", "es", 3))
    validate(payload, "common/envelope.schema.json")
    if payload["status"] == "OK":
        validate(payload["data"], "outputs/financial_concepts.schema.json")


def test_the_registry_payload_matches_the_contracts(services, adapters):
    registry = registry_with(services, adapters, FakeKnowledgeBase())
    outcome = registry.invoke(
        ToolCall("c1", "search_financial_concepts", {"query": "What is an ETF?", "lang": "en"}), ToolContext("s", "camila"),
        max_tier=Tier.T0, allow_stateful=False,
    )
    validate(outcome.payload, "common/envelope.schema.json")
    validate(outcome.payload["data"], "outputs/financial_concepts.schema.json")
    invalid = registry.invoke(
        ToolCall("c2", "search_financial_concepts", {"query": "etf", "k": 9}), ToolContext("s", "camila"), max_tier=Tier.T0, allow_stateful=False,
    )
    assert invalid.payload["status"] == "INVALID_INPUT" and invalid.payload["field"] == "k"
    validate(invalid.payload, "common/envelope.schema.json")
