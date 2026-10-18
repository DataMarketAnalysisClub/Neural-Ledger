import ast
import copy
import json
import re
from dataclasses import replace
from datetime import date
from pathlib import Path

import jsonschema
import pytest

from neural_ledger.adapters.outbound.fixtures.ledger_source import parse_ledger
from neural_ledger.bootstrap.container import build
from neural_ledger.domain.finance.estimation import estimate_model
from neural_ledger.domain.finance.params import FC_0_1
from neural_ledger.domain.ledger.entities import IncomeProfile, IncomeType
from neural_ledger.domain.shared.envelope import Caveat, Envelope, Fact
from neural_ledger.domain.shared.errors import InvalidInput
from tests.conftest import CONTRACTS, LEDGERS, make_settings
from tests.unit.test_estimation_edges import base_transactions, cycles, estimate, snapshot, txn
from tests.unit.test_estimation_recurring import _monthly, _without_rent

ROOT = Path(__file__).resolve().parents[2] / "src/neural_ledger"
CATALOG = json.loads((CONTRACTS / "catalog/financial_core.catalog.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((CONTRACTS / "catalog/catalog.schema.json").read_text(encoding="utf-8"))


def _template(node: ast.expr) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(part.value if isinstance(part, ast.Constant) else "{" + ast.unparse(part.value) + "}" for part in node.values)
    raise AssertionError(f"dynamic catalog emission at {getattr(node, 'lineno', '?')}: {ast.unparse(node)}")


def _field_sample(node: ast.expr, function: str) -> tuple[str, ...]:
    template = _template(node)
    if "{" not in template:
        return (template,)
    parents = {"_account": "accounts[0]", "_transaction": "transactions[0]", "_installment": "transactions[0].installment", "_goal": "goals[0]", "_bucket": "buckets[0]"}
    for key, value in (("{path}", parents.get(function, "transactions[0]")), ("{i}", "0")):
        template = template.replace(key, value)
    if "{name}" in template and function == "validate_snapshot":
        return tuple(template.replace("{name}", name) for name in ("target_amount", "saved_amount"))
    assert "{" not in template, (function, template)
    return (template,)


def _sites(extra_emission: str = "") -> tuple[set[str], set[str], set[str]]:
    facts, warnings, fields = set(), set(), set()
    paths = [*sorted((ROOT / "domain/finance").glob("*.py")), ROOT / "application/use_cases/financial.py", ROOT / "adapters/outbound/fixtures/ledger_source.py"]
    for path in paths:
        source = path.read_text(encoding="utf-8")
        if path.name in {"financial.py", "ledger_source.py"}:
            source += "\n" + extra_emission
        tree = ast.parse(source)
        for function in (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
            for node in ast.walk(function):
                if isinstance(node, ast.Return) and function.name == "validate_snapshot" and isinstance(node.value, ast.Tuple) and node.value.elts:
                    fields.update(_field_sample(node.value.elts[0], function.name))
                if not isinstance(node, ast.Call) or not node.args or not isinstance(node.func, ast.Name):
                    continue
                name = node.func.id
                if path.name == "ledger_source.py" and name == "_get" and len(node.args) == 3 and function.name != "_list":
                    key = _template(node.args[1])
                    parent = node.args[2]
                    prefix = _template(parent) if isinstance(parent, ast.Constant) else {
                        "_account": "accounts[0]", "_transaction": "transactions[0]", "_installment": "transactions[0].installment",
                        "_goal": "goals[0]", "_bucket": "buckets[0]",
                    }[function.name]
                    fields.add(f"{prefix}.{key}" if prefix else key)
                if path.name == "ledger_source.py" and name == "_list":
                    fields.add(_template(node.args[1]))
                if name == "Fact":
                    facts.add(_template(node.args[0]))
                elif name in ("Caveat", "_caveat") and not (function.name == "_caveat" and isinstance(node.args[0], ast.Name) and node.args[0].id == "code"):
                    warnings.add(_template(node.args[0]))
                elif name == "InvalidInput":
                    first = node.args[0]
                    if isinstance(first, (ast.Constant, ast.JoinedStr)):
                        fields.update(_field_sample(first, function.name))
                    else:
                        assert isinstance(first, ast.Name) and first.id in {"field", "path", "key"} and function.name in {
                            "_get", "_int", "_str", "_enum", "_date", "_month", "_list", "_parse_enum", "_parse_int", "_parse_month",
                        } or function.name == "_get" and isinstance(first, ast.IfExp) or function.name == "load" and isinstance(first, ast.BoolOp), (path, function.name, ast.unparse(first))
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and node.value.args:
                name = node.value.func.id if isinstance(node.value.func, ast.Name) else ""
                if name == "Fact":
                    facts.add(_template(node.value.args[0]))
                elif name == "Caveat":
                    warnings.add(_template(node.value.args[0]))
                elif name == "InvalidInput":
                    fields.update(_field_sample(node.value.args[0], ""))
    return facts, warnings, fields


def _match(entry: dict, value: str) -> bool:
    return re.fullmatch(entry["pattern"], value) is not None


def _validate_static(extra_emission: str = "") -> None:
    jsonschema.Draft202012Validator(SCHEMA).validate(CATALOG)
    facts, warnings, fields = _sites(extra_emission)
    assert facts == {entry["template"] for entry in CATALOG["facts"]}
    assert warnings == {entry["code"] for entry in CATALOG["warnings"]}
    assert len(facts) == len(CATALOG["facts"])
    assert len(warnings) == len(CATALOG["warnings"])
    for field in fields:
        assert sum(_match(entry, field) for entry in CATALOG["error_fields"] if entry["status"] == "INVALID_INPUT") == 1, field


def test_catalog_schema_and_static_emissions_are_in_sync():
    _validate_static()


@pytest.mark.parametrize("emission, kind", [
    ("Fact('zz.uncatalogued', 1, 'count', 'test')", "facts"),
    ("Caveat('NEW_WARNING', 'test')", "warnings"),
    ("InvalidInput('new_field', 'test')", "fields"),
    ("def validate_snapshot():\n    return ('new_field', 'invalid', ())", "fields"),
    ("def validate_snapshot():\n    return (f'transactions[{0}].new_field', 'invalid', ())", "fields"),
    ("def _goal(g, path):\n    return _get(g, 'new_field', path)", "fields"),
])
def test_static_scan_detects_an_uncatalogued_source_emission(emission, kind):
    with pytest.raises(AssertionError):
        _validate_static(emission)


def _check(envelope, *, estimation: bool = False) -> set[str]:
    for fact in envelope.facts:
        matches = [entry for entry in CATALOG["facts"] if _match(entry, fact.key)]
        assert len(matches) == 1 and fact.unit == matches[0]["unit"], (fact.key, fact.unit)
    for warning in envelope.warnings:
        matches = [item for item in CATALOG["warnings"] if item["code"] == warning.code]
        assert len(matches) == 1, warning.code
        entry = matches[0]
        assert bool(warning.must_mention) == entry["must_mention"]
        assert entry["reaches_tool_envelope"] is not estimation
    if envelope.field:
        assert any(_match(entry, envelope.field) for entry in CATALOG["error_fields"] if entry["status"] == "INVALID_INPUT")
    for missing in envelope.missing:
        assert any(_match(entry, missing) for entry in CATALOG["error_fields"] if entry["status"] == "INSUFFICIENT_DATA")
    return {warning.code for warning in envelope.warnings}


def test_runtime_guard_rejects_new_emissions_and_wrong_unit():
    services, _ = build(make_settings())
    real = services.financial.financial_state("camila")
    cases = (
        replace(real, facts=(*real.facts, Fact("zz.uncatalogued", 1, "count", "test"))),
        replace(real, facts=(replace(real.facts[0], unit="count"),)),
        replace(real, warnings=(Caveat("NEW_WARNING", "test"),)),
        Envelope.invalid("new_field", (), params_version=FC_0_1.version, message="test"),
    )
    for envelope in cases:
        with pytest.raises(AssertionError):
            _check(envelope)


@pytest.mark.parametrize("source", ["fixture", "ledger"])
@pytest.mark.parametrize("persona", ["camila", "diego"])
def test_tool_fact_matrix_and_forwarded_warnings(source, persona):
    services, _ = build(make_settings(model_source=source))
    financial = services.financial
    calls = [financial.financial_state(persona), financial.commitments(persona), financial.forecast(persona),
             financial.simulate_purchase(persona, 400_000, 12), financial.protected_surplus(persona),
             financial.capacity(persona), financial.permitted_profile(persona, "conservative"),
             financial.savings_plan(persona, "aggressive")]
    codes = set().union(*(_check(envelope) for envelope in calls))
    assert {"RATE_ASSUMED", "FIRST_INSTALLMENT_ASSUMED"} <= codes
    if persona == "camila":
        assert "PROFILE_CAPPED" in codes
    assert _check(financial.simulate_purchase(persona, 400_000, 49)) == set()
    assert _check(financial.forecast("nobody")) == set()


def test_estimation_warning_matrix_and_adapter_gap():
    raw = json.loads((LEDGERS / "camila.json").read_text(encoding="utf-8"))
    cases = []
    cases.append(estimate_model(parse_ledger(raw), FC_0_1))
    changed = copy.deepcopy(raw)
    changed["transactions"].append(copy.deepcopy(changed["transactions"][8]))
    cases.append(estimate_model(parse_ledger(changed), FC_0_1))
    near = copy.deepcopy(raw)
    near["transactions"].append({**near["transactions"][8], "txn_id": "near_copied"})
    cases.append(estimate_model(parse_ledger(near), FC_0_1))
    last = cycles(8)[-1]
    cases.append(estimate([*base_transactions(8), txn(date(last.year, last.month, 12), -20_000, "SHOP CUOTA", "shopping")], FC_0_1))
    cases.append(estimate(base_transactions(8, skip_salary=(cycles(8)[-1],)), FC_0_1))
    cases.append(estimate(base_transactions(8, salary=900_000), FC_0_1))
    cases.append(estimate_model(snapshot(base_transactions(8), income=IncomeProfile(IncomeType.SALARIED, None, "last_business_day")), FC_0_1))
    first = cycles(8)[0]
    cases.append(estimate([*base_transactions(8), txn(date(first.year, first.month, 12), -15_000, "GIFT", "gifts")], FC_0_1))
    months = cycles(11)
    old = _monthly("LANDLORD A", [500_000] * 9, months[:9])
    new = _monthly("LANDLORD B", [550_000] * 2, months[9:])
    cases.append(estimate(_without_rent(11) + old + new, FC_0_1))
    seen = set().union(*(_check(envelope, estimation=True) for envelope in cases))
    assert {entry["code"] for entry in CATALOG["warnings"] if entry["source"] == "estimation"} <= seen
    services, _ = build(make_settings(model_source="ledger"))
    assert not services.financial.forecast("camila").warnings


def test_error_field_patterns_have_real_producers():
    raw = json.loads((LEDGERS / "camila.json").read_text(encoding="utf-8"))
    mutations = (
        lambda item: item.update(currency="USD"),
        lambda item: item.update(as_of="2026-10-15"),
        lambda item: item["accounts"][0].update(balance=10**12),
        lambda item: item["buckets"][0].update(amount=-1),
        lambda item: item["goals"][0].update(target_amount=-1),
        lambda item: item["income_profile"].update(contracted_net=-1),
        lambda item: item["transactions"][0].update(kind="unknown"),
        lambda item: item.pop("user_id"),
    )
    fields: set[str] = set()
    for mutate in mutations:
        changed = copy.deepcopy(raw)
        mutate(changed)
        try:
            envelope = estimate_model(parse_ledger(changed), FC_0_1)
        except InvalidInput as exc:
            fields.add(exc.field)
        else:
            assert envelope.field
            fields.add(envelope.field)
    services, _ = build(make_settings())
    fields.add(services.financial.simulate_purchase("camila", 400_000, 49).field)
    try:
        parse_ledger(None)
    except InvalidInput as exc:
        fields.add(exc.field)
    assert all(any(_match(entry, field) for field in fields) for entry in CATALOG["error_fields"] if entry["status"] == "INVALID_INPUT"), fields
    insufficient = estimate([], FC_0_1).missing + services.financial.forecast("nobody").missing
    assert all(any(_match(entry, field) for field in insufficient) for entry in CATALOG["error_fields"] if entry["status"] == "INSUFFICIENT_DATA")


@pytest.mark.parametrize("section, key", [
    ("goals", "name"), ("goals", "goal_id"), ("goals", "deadline"),
    ("goals", "target_amount"), ("goals", "saved_amount"),
    ("buckets", "bucket"), ("buckets", "amount"),
    ("accounts", "account_id"), ("accounts", "type"),
    ("transactions", "txn_id"), ("transactions", "kind"),
])
def test_missing_nested_ledger_field_is_catalogued(section, key):
    raw = json.loads((LEDGERS / "camila.json").read_text(encoding="utf-8"))
    del raw[section][0][key]
    with pytest.raises(InvalidInput) as error:
        parse_ledger(raw)
    assert error.value.field == f"{section}[0].{key}"
    _check(Envelope.invalid(error.value.field, (), params_version=FC_0_1.version, message="missing"))


@pytest.mark.parametrize("section", ["accounts", "transactions", "goals", "buckets"])
def test_scalar_ledger_section_item_is_catalogued(section):
    raw = json.loads((LEDGERS / "camila.json").read_text(encoding="utf-8"))
    raw[section][0] = 7
    with pytest.raises(InvalidInput) as error:
        parse_ledger(raw)
    assert error.value.field == f"{section}[0]"
    _check(Envelope.invalid(error.value.field, (), params_version=FC_0_1.version, message="object required"))


@pytest.mark.parametrize("key", ["plan_id", "installment_number", "installment_total", "original_amount"])
def test_missing_installment_field_is_catalogued(key):
    raw = json.loads((LEDGERS / "camila.json").read_text(encoding="utf-8"))
    index = next(i for i, txn_data in enumerate(raw["transactions"]) if txn_data["installment"] is not None)
    del raw["transactions"][index]["installment"][key]
    with pytest.raises(InvalidInput) as error:
        parse_ledger(raw)
    assert error.value.field == f"transactions[{index}].installment.{key}"
    _check(Envelope.invalid(error.value.field, (), params_version=FC_0_1.version, message="missing"))


@pytest.mark.parametrize("key", ["user_id", "currency", "as_of", "accounts", "transactions", "income_profile"])
def test_missing_required_top_level_field_is_catalogued(key):
    raw = json.loads((LEDGERS / "camila.json").read_text(encoding="utf-8"))
    del raw[key]
    with pytest.raises(InvalidInput) as error:
        parse_ledger(raw)
    assert error.value.field == key
    _check(Envelope.invalid(error.value.field, (), params_version=FC_0_1.version, message="missing"))
