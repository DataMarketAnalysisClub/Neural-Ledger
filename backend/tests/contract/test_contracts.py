"""Contract tests: real outputs validate against contracts/, and code and contracts agree."""

from __future__ import annotations

import json
from importlib.util import find_spec

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
    validate(to_primitive(services.financial.simulate_purchase("camila", 400_000, 49)), "common/envelope.schema.json")
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


def test_statement_outputs_and_audit_match_contracts(services):
    pytest.importorskip("pymupdf")
    pytest.importorskip("pdfplumber")
    from tests.statement_samples import Sample, santander_pdf

    unverified = santander_pdf(Sample(daily_override={"04/12": 1}))
    imported = to_primitive(services.statements.import_statement("camila", unverified))
    validate(imported, "common/envelope.schema.json")
    validate(imported["data"], "outputs/statement_import.schema.json")
    assert imported["data"]["imports"][0]["statement"]["issues"], "the unverified path must be covered too"
    assert imported["data"]["imports"][0]["redaction"]["counts"], "the redaction block must be covered with counts"

    duplicate = to_primitive(services.statements.import_statement("camila", unverified))
    validate(duplicate["data"], "outputs/statement_import.schema.json")
    assert duplicate["data"]["imports"][0]["duplicate"] and duplicate["data"]["imports"][0]["redaction"] is None

    listed = to_primitive(services.statements.list_statements("camila"))
    validate(listed, "common/envelope.schema.json")
    validate(listed["data"], "outputs/statements.schema.json")

    detail = to_primitive(services.statements.get_statement("camila", imported["data"]["imports"][0]["statement"]["statement_id"]))
    validate(detail, "common/envelope.schema.json")
    validate(detail["data"], "outputs/statement.schema.json")

    validate(to_primitive(services.statements.import_statement("camila", b"not a statement")), "common/envelope.schema.json")

    # Same lines as the unverified one above, so the same statement_id: import it as another user.
    verified = to_primitive(services.statements.import_statement("diego", santander_pdf()))
    validate(verified["data"], "outputs/statement_import.schema.json")
    transactions = to_primitive(services.ledger.list_transactions("diego"))
    validate(transactions, "common/envelope.schema.json")
    validate(transactions["data"], "outputs/transactions.schema.json")
    if find_spec("sklearn"):
        assert transactions["data"]["transactions"], "the posted path must be covered too"
    for event in services.audit.raw():
        validate(event.to_record(), "audit/audit_event.schema.json")


def test_card_and_spreadsheet_statements_match_contracts(services):
    """Card statements (obligations, cuotas, kinds), provisional Excel exports and their ledger rows."""
    pytest.importorskip("pymupdf")
    pytest.importorskip("pdfplumber")
    from tests.statement_samples import CardSample, bice_xlsx, card_pdf, santander_xlsx

    for content in (card_pdf(), card_pdf(CardSample(upcoming=(1, 2, 0, 0))), bice_xlsx(), santander_xlsx()):
        imported = to_primitive(services.statements.import_statement("camila", content))
        validate(imported, "common/envelope.schema.json")
        validate(imported["data"], "outputs/statement_import.schema.json")
        for entry in imported["data"]["imports"]:
            detail = to_primitive(services.statements.get_statement("camila", entry["statement"]["statement_id"]))
            validate(detail["data"], "outputs/statement.schema.json")
    validate(to_primitive(services.statements.list_statements("camila"))["data"], "outputs/statements.schema.json")
    transactions = to_primitive(services.ledger.list_transactions("camila"))
    validate(transactions["data"], "outputs/transactions.schema.json")
    if find_spec("sklearn"):
        kinds = {t["kind"] for t in transactions["data"]["transactions"]}
        assert {"card_payment", "refund", "fee", "purchase", "income"} <= kinds
        assert any(t["installment"] for t in transactions["data"]["transactions"])


def test_transaction_categories_match_the_domain_vocabulary():
    from neural_ledger.domain.ledger.categorization import CATEGORIES, INCOME, OWN_MONEY, UNCATEGORIZED, user_categories
    from neural_ledger.domain.ledger.entities import TransactionKind

    schema = json.loads((CONTRACTS / "outputs/transactions.schema.json").read_text())
    assert set(schema["$defs"]["category"]["enum"]) == CATEGORIES | OWN_MONEY | {INCOME, UNCATEGORIZED}
    update = json.loads((CONTRACTS / "transactions/category_update.schema.json").read_text())
    assert set(update["properties"]["category"]["enum"]) == set().union(*(user_categories(k) for k in TransactionKind))
    posted_kinds = {TransactionKind.INCOME, TransactionKind.PURCHASE, TransactionKind.CARD_PAYMENT, TransactionKind.REFUND, TransactionKind.FEE}
    assert set(schema["properties"]["transactions"]["items"]["properties"]["kind"]["enum"]) == {k.value for k in posted_kinds}


def _part(relative: str, pointer: str):
    """A validator for one part of a contract, e.g. a single property."""
    return jsonschema.Draft202012Validator({"$ref": (CONTRACTS / relative).resolve().as_uri() + pointer}, registry=REGISTRY)


def test_redaction_placeholders_match_the_domain_codes():
    from neural_ledger.domain.privacy.redaction import PLACEHOLDER_CODES

    schema = json.loads((CONTRACTS / "common/redaction.schema.json").read_text(encoding="utf-8"))
    assert tuple(schema["enum"]) == PLACEHOLDER_CODES
    counts = _part("outputs/statement_import.schema.json", "#/$defs/imported/properties/redaction/properties/counts")
    assert counts.is_valid({"PERSON": 1, "NUMBER": 3})
    assert not counts.is_valid({"SECRET": 1})  # a code the clients do not know is a contract breach
    assert not counts.is_valid({"PERSON": 0})  # codes with none are left out


@pytest.mark.parametrize(
    "relative, pointer, masked, raw",
    [
        ("outputs/statement.schema.json", "#/$defs/summary/properties/account_ref", "****3456", "0-000-00-12345-6"),
        (
            "outputs/transactions.schema.json",
            "#/properties/transactions/items/properties/account_id",
            "santander_cl_cuentamatica:****3456",
            "santander_cl_cuentamatica:0-000-00-12345-6",
        ),
    ],
)
def test_account_references_must_be_masked(relative, pointer, masked, raw):
    account = _part(relative, pointer)
    assert account.is_valid(masked) and not account.is_valid(raw)
