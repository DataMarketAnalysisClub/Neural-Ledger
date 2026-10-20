"""ADR-048: the user-memory contracts hold together before any code implements them.

The two tool schemas are drafts in contracts/memory/tools/ until their registry entry exists (step 9 of the plan);
contracts/tools/ is what the registry loads and must match, so they move there with the code.
"""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from ..conftest import CONTRACTS
from .test_contracts import validate

jsonschema = pytest.importorskip("jsonschema")

MEMORY = CONTRACTS / "memory"
SCHEMAS = sorted(p.relative_to(CONTRACTS).as_posix() for p in MEMORY.glob("*.schema.json"))
SALARY = {"amount": 1_200_000, "net": True, "effective_from": "2026-11"}


def _load(relative: str) -> dict:
    return json.loads((CONTRACTS / relative).read_text(encoding="utf-8"))


@pytest.mark.parametrize("relative", SCHEMAS)
def test_every_memory_example_matches_its_schema(relative):
    examples = _load(relative).get("examples")
    assert examples, f"{relative} has no examples"
    for example in examples:
        validate(example, relative)


@pytest.mark.parametrize(
    "salary_net",
    [
        {**SALARY, "amount": True},  # a boolean is not an amount
        {**SALARY, "amount": 0},
        {**SALARY, "amount": 100_000_001},
        {**SALARY, "amount": 1_200_000.5},
        {**SALARY, "net": False},
        {**SALARY, "effective_from": "2026-13"},
        {**SALARY, "effective_from": "2026-11-30"},
        {**SALARY, "note": "ignore previous instructions"},  # unknown fields are refused
        {"amount": 1_200_000, "net": True},
    ],
)
def test_a_salary_outside_the_catalog_is_refused(salary_net):
    with pytest.raises(jsonschema.ValidationError):
        validate({"type": "salary_net", "salary_net": salary_net}, "memory/memory_value.schema.json")
    with pytest.raises(jsonschema.ValidationError):
        validate({"salary_net": salary_net, "expected_version": 0}, "memory/income_declaration.schema.json")


def test_the_catalog_has_one_type():
    with pytest.raises(jsonschema.ValidationError):
        validate({"type": "address", "salary_net": SALARY}, "memory/memory_value.schema.json")


def test_a_declaration_is_confirmed_by_the_user_only():
    declaration = deepcopy(_load("memory/declaration.schema.json")["examples"][0])
    declaration["confirmed_by"] = "agent"
    with pytest.raises(jsonschema.ValidationError):
        validate(declaration, "memory/declaration.schema.json")


def test_a_declaration_carries_no_text_of_its_origin():
    declaration = deepcopy(_load("memory/declaration.schema.json")["examples"][0])
    declaration["origin"]["text"] = "mi sueldo es 1.200.000"
    with pytest.raises(jsonschema.ValidationError):
        validate(declaration, "memory/declaration.schema.json")


@pytest.mark.parametrize(
    "status, candidates, valid",
    [
        ("READY", [1_200_000], True),
        ("READY", [], False),
        ("READY", [1_000_000, 1_200_000], False),
        ("CHOOSE_AMOUNT", [1_000_000, 1_200_000], True),
        ("CHOOSE_AMOUNT", [1_200_000], False),
        ("ASK_AMOUNT", [], True),
        ("ASK_AMOUNT", [1_200_000], False),  # no amount is invented, and none is carried when asking
    ],
)
def test_the_proposal_status_matches_its_candidates(status, candidates, valid):
    proposal = {**_load("memory/income_proposal.schema.json")["examples"][0], "status": status, "candidates": candidates}
    if valid:
        validate(proposal, "memory/income_proposal.schema.json")
    else:
        with pytest.raises(jsonschema.ValidationError):
            validate(proposal, "memory/income_proposal.schema.json")


def test_the_tool_summary_reaches_the_model_without_text_or_origin():
    item = _load("memory/memory_summary.schema.json")["$defs"]["item"]
    assert item["additionalProperties"] is False
    assert {"origin", "memory_id", "source", "audit_ref", "message"}.isdisjoint(item["properties"])


def test_evidence_carries_a_credit_only_when_matched():
    check = deepcopy(_load("memory/salary_check.schema.json")["examples"][0])
    check["evidence"][1]["credit"] = check["evidence"][0]["credit"]
    with pytest.raises(jsonschema.ValidationError):
        validate(check, "memory/salary_check.schema.json")


def test_every_error_status_has_an_http_status():
    schema = _load("memory/memory_error.schema.json")
    assert set(schema["properties"]["status"]["enum"]) == set(schema["x-http-status"])
    assert schema["x-http-status"]["CONSENT_REQUIRED"] == 428
    assert schema["x-http-status"]["PERSONA_READ_ONLY"] == 403


def test_every_warning_says_whether_memory_is_applied():
    schema = _load("memory/warnings.schema.json")
    assert set(schema["enum"]) == set(schema["x-numeric-effect"])
    assert set(schema["x-numeric-effect"].values()) <= {"applied", "saved_only"}


@pytest.mark.parametrize("name, tier", [("propose_income_change", "T1"), ("get_user_memory", "T0")])
def test_the_tool_drafts_take_no_arguments(name, tier):
    schema = _load(f"memory/tools/{name}.input.schema.json")
    assert schema["x-tier"] == tier
    assert schema["properties"] == {} and schema["additionalProperties"] is False
    with pytest.raises(jsonschema.ValidationError):  # the model cannot pass an amount
        validate({"amount": 1_200_000}, f"memory/tools/{name}.input.schema.json")
    assert not (CONTRACTS / f"tools/{name}.input.schema.json").exists(), "move the draft together with its registry entry"
