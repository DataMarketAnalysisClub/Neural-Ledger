"""ADR-017 (Proposed): in ledger mode, financial tool envelopes and the chat turn carry the
stage-1 estimator's facts and warnings. The fixture source (the default) forwards nothing."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from neural_ledger.adapters.outbound.fixtures import ledger_source
from neural_ledger.application.conversation import ModelTurn, ToolCall
from neural_ledger.application.use_cases.financial import FinancialUseCases
from neural_ledger.bootstrap.container import build
from neural_ledger.domain.audit.events import AuditKind
from neural_ledger.domain.shared.serialization import to_primitive
from tests.conftest import DATA, LEDGERS, make_settings
from tests.security.helpers import ScriptedFakeLLM, chat_with, say

SEASONAL = "SEASONALITY_UNOBSERVED"
UNOBSERVED = "estimate.seasonal.unobserved_months"
SHORT_SINCE = "2026-02-27"  # payday of 2026-02: keeps cycles 2026-03 .. 2026-10, no December
SNAPSHOT = re.compile(r"tool_snapshot=([a-z]+_[0-9a-f]{16})$")


def write_data_dir(root: Path, ledger: dict) -> Path:
    """A data dir with the real persona profiles and one ledger (the container needs both)."""
    shutil.copytree(DATA / "personas", root / "personas")
    (root / "ledgers").mkdir()
    (root / "ledgers" / f"{ledger['user_id']}.json").write_text(json.dumps(ledger), encoding="utf-8")
    return root


def short_ledger(persona: str = "camila") -> dict:
    raw = json.loads((LEDGERS / f"{persona}.json").read_text(encoding="utf-8"))
    raw["transactions"] = [t for t in raw["transactions"] if t["date"] >= SHORT_SINCE]
    return raw


@pytest.fixture
def short(tmp_path):
    """(services, adapters) in ledger mode over an 8-cycle camila ledger."""
    return build(make_settings(data_dir=write_data_dir(tmp_path, short_ledger()), model_source="ledger"))


def test_short_history_ledger_is_estimable_and_flags_seasonality(short):
    _, adapters = short
    model, evidence = adapters.source.load_with_evidence("camila")
    assert model.spend.window_months == 8
    assert SEASONAL in {w.code for w in evidence.warnings}
    assert next(f for f in evidence.facts if f.key == UNOBSERVED).value == "12"


@pytest.mark.parametrize("tool", ["financial_state", "forecast", "capacity", "commitments", "protected_surplus"])
def test_tools_carry_the_seasonality_warning_and_fact(short, tool):
    services, adapters = short
    _, evidence = adapters.source.load_with_evidence("camila")
    envelope = getattr(services.financial, tool)("camila")
    assert envelope.ok
    assert envelope.warnings[-len(evidence.warnings):] == evidence.warnings
    fact = next(f for f in envelope.facts if f.key == UNOBSERVED)
    assert (fact.value, fact.unit) == ("12", "month_numbers")
    assert fact.derivation.endswith(f"estimator_snapshot={evidence.snapshot_id}; tool_snapshot={envelope.snapshot_id}")


def test_the_estimator_runs_once_per_tool_call(short, monkeypatch):
    services, _ = short
    calls = []
    real = ledger_source.estimate_model

    def counting(snapshot, params):
        calls.append(snapshot.user_id)
        return real(snapshot, params)

    monkeypatch.setattr(ledger_source, "estimate_model", counting)
    for tool in (services.financial.forecast, services.financial.capacity, services.financial.savings_plan):
        calls.clear()
        assert tool("camila").ok
        assert calls == ["camila"]


def test_non_ok_envelopes_carry_no_evidence(short):
    services, _ = short
    invalid = services.financial.forecast("camila", horizon_months=99)
    unknown = services.financial.forecast("nobody")
    for envelope in (invalid, unknown):
        assert not envelope.ok
        assert envelope.facts == () and envelope.warnings == ()


def test_insufficient_ledger_carries_no_evidence(tmp_path):
    raw = json.loads((LEDGERS / "camila.json").read_text(encoding="utf-8"))
    raw["transactions"] = [t for t in raw["transactions"] if t["date"] >= "2026-07-30"]  # cycles 2026-07 .. 2026-10: 4 < 6
    services, _ = build(make_settings(data_dir=write_data_dir(tmp_path, raw), model_source="ledger"))
    envelope = services.financial.forecast("camila")
    assert envelope.status.value == "INSUFFICIENT_DATA"
    assert envelope.facts == () and envelope.warnings == ()


def test_same_key_facts_from_two_tools_stay_distinct_in_one_chat_turn(short):
    services, adapters = short
    _, evidence = adapters.source.load_with_evidence("camila")
    both = ModelTurn(None, (ToolCall("c1", "forecast_cashflow", {}), ToolCall("c2", "get_financial_state", {})), "fake")
    llm = ScriptedFakeLLM([both, say("")])
    reply = chat_with(services, adapters, llm).handle("s-collide", "camila", "Will I be OK in December?")
    assert reply.tools_called == ("forecast_cashflow", "get_financial_state")
    for original in evidence.facts:
        copies = [f for f in reply.facts if f.key == original.key]
        assert len(copies) == 2, original.key  # nothing dropped, nothing merged
        assert {(f.value, f.unit) for f in copies} == {(original.value, original.unit)}
        snapshots = {SNAPSHOT.search(f.derivation).group(1) for f in copies}
        assert len(snapshots) == 2 and all(s.startswith(("forecast_", "state_")) for s in snapshots)
    assert [w.code for w in reply.warnings].count(SEASONAL) == 2  # one per tool envelope


def test_omitted_forwarded_warning_is_rejected_and_replaced_by_a_verified_fallback(short):
    services, adapters = short
    llm = ScriptedFakeLLM([ModelTurn(None, (ToolCall("c1", "forecast_cashflow", {}),), "fake"), say("Your forecast looks fine.")])
    reply = chat_with(services, adapters, llm).handle("s-omit", "camila", "Will I be OK in December?")
    failures = [e.draft for e in adapters.audit_log.events() if e.draft.kind is AuditKind.VERIFICATION_FAILED]
    assert len(failures) == 1
    assert f"MISSING_WARNING:{SEASONAL}" in failures[0].detail
    assert reply.fallback_used is True
    assert reply.text != "Your forecast looks fine."
    assert "December" in reply.text and "seasonal" in reply.text
    assert reply.verification is not None and reply.verification.ok


def test_a_reply_that_mentions_the_forwarded_warnings_passes(short):
    services, adapters = short
    _, evidence = adapters.source.load_with_evidence("camila")
    text = "Your forecast is ready. " + " ".join(w.message for w in evidence.warnings)
    llm = ScriptedFakeLLM([ModelTurn(None, (ToolCall("c1", "forecast_cashflow", {}),), "fake"), say(text)])
    reply = chat_with(services, adapters, llm).handle("s-mention", "camila", "Will I be OK in December?")
    assert reply.fallback_used is False and reply.text == text
    assert reply.verification.ok


def test_large_duplicate_count_has_a_verified_chat_fallback(tmp_path):
    raw = short_ledger()
    raw["transactions"].extend([raw["transactions"][0].copy() for _ in range(1000)])
    services, adapters = build(make_settings(data_dir=write_data_dir(tmp_path, raw), model_source="ledger"))
    tool = services.financial.forecast("camila")
    assert tool.ok and any(w.code == "DUPLICATE_TXN_ID" for w in tool.warnings)
    llm = ScriptedFakeLLM([ModelTurn(None, (ToolCall("c1", "forecast_cashflow", {}),), "fake"), say("Your forecast looks fine.")])

    reply = chat_with(services, adapters, llm).handle("s-large-count", "camila", "Will I be OK in December?")

    failures = [event.draft for event in adapters.audit_log.events() if event.draft.kind is AuditKind.VERIFICATION_FAILED]
    assert len(failures) == 1 and "MISSING_WARNING:DUPLICATE_TXN_ID" in failures[0].detail
    assert reply.fallback_used and reply.verification.ok
    assert any(w.code == "DUPLICATE_TXN_ID" for w in reply.warnings)


def test_fixture_mode_forwards_nothing_and_is_unchanged():
    services, _ = build(make_settings())
    f = services.financial
    assert f._evidence is None
    plain = FinancialUseCases(f._source, f._snapshots, f._bank, f._profiles, f.params)
    for call in (
        lambda uc: uc.financial_state("camila"),
        lambda uc: uc.commitments("camila"),
        lambda uc: uc.forecast("camila"),
        lambda uc: uc.simulate_purchase("camila", 400_000, 12),
        lambda uc: uc.protected_surplus("camila"),
        lambda uc: uc.capacity("camila"),
        lambda uc: uc.permitted_profile("camila", "conservative"),
        lambda uc: uc.savings_plan("camila", "aggressive"),
    ):
        wired, bare = call(f), call(plain)
        assert to_primitive(wired) == to_primitive(bare)
        assert not any(fact.key.startswith("estimate.") for fact in wired.facts)
