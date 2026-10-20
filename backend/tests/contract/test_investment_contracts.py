"""The investment contracts (ADR-044) validate what the code produces, and their examples validate too."""

from __future__ import annotations

import json
import re

import pytest

from neural_ledger.domain.shared.serialization import to_primitive

from ..conftest import CONTRACTS

jsonschema = pytest.importorskip("jsonschema")
from tests.contract.test_contracts import validate  # noqa: E402

USER = "usr_contract"


@pytest.mark.parametrize("relative", ["investments/link_request.schema.json", "investments/link_outcome.schema.json"])
def test_examples_validate(relative):
    schema = json.loads((CONTRACTS / relative).read_text(encoding="utf-8"))
    assert schema["examples"]
    for example in schema["examples"]:
        validate(example, relative)


def test_overview_link_outcomes_and_audit_events_match(services):
    assert services.investments.overview(USER).missing == ("investment_account",)
    validate(to_primitive(services.investments.overview(USER)), "common/envelope.schema.json")
    for outcome in (
        services.investments.link(USER, "sess", "contract@example.invalid", "synthetic-password", consent=True),
        services.investments.status(USER),
        services.investments.sync(USER, "sess"),
    ):
        validate(to_primitive(outcome), "investments/link_outcome.schema.json")
    overview = to_primitive(services.investments.overview(USER))
    validate(overview, "common/envelope.schema.json")
    validate(overview["data"], "outputs/investments.schema.json")
    validate(to_primitive(services.investments.unlink(USER, "sess")), "investments/link_outcome.schema.json")
    for event in services.audit.raw():
        validate(event.to_record(), "audit/audit_event.schema.json")


def test_the_overview_contract_names_every_fact_and_warning_the_code_emits(services):
    services.investments.link(USER, "sess", "contract@example.invalid", "synthetic-password", consent=True)
    description = json.loads((CONTRACTS / "outputs/investments.schema.json").read_text(encoding="utf-8"))["description"]
    overview = services.investments.overview(USER)
    goal_facts = "investments.goal.<goal_id>.value|deposited|gain"
    assert goal_facts in description
    for fact in overview.facts:
        if fact.key.startswith("investments.goal."):
            assert re.fullmatch(r"investments\.goal\.[A-Za-z0-9_-]+\.(value|deposited|gain)", fact.key), fact.key
        else:
            assert fact.key in description, fact.key
    for warning in overview.warnings:
        assert warning.code in description


def test_imported_statements_match_the_contracts_and_name_every_fact_and_warning(services):
    pytest.importorskip("pymupdf")
    from tests.investment_samples import holdings_pdf, movements_pdf

    results = [services.documents.ingest(USER, content, "sess", investments=True) for content in (holdings_pdf(), movements_pdf(), movements_pdf())]
    results.append(services.documents.ingest(USER, holdings_pdf(total_delta=5), "sess", investments=True))  # unverified
    for result in results:
        payload = to_primitive(result)
        validate(payload, "common/envelope.schema.json")
        validate(payload["data"], "outputs/document_ingest.schema.json")
        validate(payload["data"]["investment"], "outputs/investment_document_import.schema.json")
    overview = services.investments.overview(USER)
    validate(to_primitive(overview)["data"], "outputs/investments.schema.json")
    description = json.loads((CONTRACTS / "outputs/investments.schema.json").read_text(encoding="utf-8"))["description"]
    for fact in overview.facts:
        if fact.key.startswith("investments.goal."):
            assert re.fullmatch(r"investments\.goal\.[A-Za-z0-9_-]+\.(value|deposited|gain)", fact.key), fact.key
        elif fact.key.startswith("investments.fund."):
            assert re.fullmatch(r"investments\.fund\.[a-z0-9_]+\.value", fact.key) and "investments.fund.<fund_id>.value" in description
        else:
            assert fact.key in description, fact.key
    for warning in overview.warnings:
        assert warning.code in description
    imports = json.loads((CONTRACTS / "outputs/investment_document_import.schema.json").read_text(encoding="utf-8"))["description"]
    emitted = {w.code for r in results for w in r.warnings}
    assert {"INVESTMENT_DOCUMENT_UNVERIFIED", "INVESTMENT_DOCUMENT_DUPLICATE", "INVESTMENTS_NO_HISTORY"} <= emitted
    assert all(code in description or code in imports for code in emitted)
    for event in services.audit.raw():
        validate(event.to_record(), "audit/audit_event.schema.json")
