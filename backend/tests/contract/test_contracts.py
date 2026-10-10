"""Contract tests: real outputs validate against contracts/, and code and contracts agree."""

from __future__ import annotations

import json

import pytest

from neural_ledger.bootstrap.contracts import contract_tiers
from neural_ledger.domain.shared.serialization import to_primitive

from ..conftest import CONTRACTS

jsonschema = pytest.importorskip("jsonschema")
from referencing import Registry, Resource  # noqa: E402  (installed with jsonschema)


def _registry() -> Registry:
    resources = []
    for path in CONTRACTS.rglob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        resources.append((path.resolve().as_uri(), Resource.from_contents(schema)))
        if "$id" in schema:
            resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


REGISTRY = _registry()


def validate(instance, relative: str) -> None:
    path = (CONTRACTS / relative).resolve()
    schema = json.loads(path.read_text(encoding="utf-8"))
    schema = {**schema, "$id": path.as_uri()}
    jsonschema.Draft202012Validator(schema, registry=REGISTRY).validate(instance)


def test_every_schema_is_valid_json_schema():
    for path in CONTRACTS.rglob("*.schema.json"):
        jsonschema.Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


def test_registry_and_contracts_agree_on_tools_and_tiers(services):
    tiers = contract_tiers(CONTRACTS)
    assert set(tiers) == set(services.registry.names)
    for name, tier in tiers.items():
        assert services.registry.tier_of(name).value == tier, name


@pytest.mark.parametrize(
    "call, output_schema",
    [
        (lambda s: s.financial.financial_state("camila"), "outputs/financial_state.schema.json"),
        (lambda s: s.financial.commitments("camila"), "outputs/commitments.schema.json"),
        (lambda s: s.financial.forecast("camila"), "outputs/forecast.schema.json"),
        (lambda s: s.financial.simulate_purchase("camila", 400_000, 12), "outputs/purchase_simulation.schema.json"),
        (lambda s: s.financial.protected_surplus("camila", 6, "recommended"), "outputs/protected_surplus.schema.json"),
        (lambda s: s.financial.capacity("camila"), "outputs/capacity.schema.json"),
        (lambda s: s.financial.permitted_profile("camila", "aggressive"), "outputs/permitted_profile.schema.json"),
        (lambda s: s.financial.savings_plan("camila"), "outputs/savings_plan.schema.json"),
    ],
)
def test_outputs_match_contracts(services, call, output_schema):
    payload = to_primitive(call(services))
    validate(payload, "common/envelope.schema.json")
    validate(payload["data"], output_schema)


def test_errors_match_envelope(services):
    validate(to_primitive(services.financial.simulate_purchase("camila", 400_000, 7)), "common/envelope.schema.json")
    validate(to_primitive(services.financial.forecast("nobody")), "common/envelope.schema.json")


def test_chat_reply_and_audit_events_match(services):
    reply = services.chat.handle("s-contract", "camila", "Help me save for my trip")
    validate(to_primitive(reply), "chat/chat_reply.schema.json")
    for event in services.audit.raw():
        validate(event.to_record(), "audit/audit_event.schema.json")


def test_action_terms_example_is_what_the_plan_produces(services):
    plan = services.financial.savings_plan("camila")
    from neural_ledger.domain.actions.terms import terms_from_plan

    terms = to_primitive(terms_from_plan(plan.data, "CLP"))
    example = json.loads((CONTRACTS / "actions/action_terms.schema.json").read_text())["examples"][0]
    assert terms == example
    validate(terms, "actions/action_terms.schema.json")
