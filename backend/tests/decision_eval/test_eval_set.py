"""The evaluation set stays well formed, and the offline runner works on it (no network, no key)."""

from __future__ import annotations

from collections import Counter

from neural_ledger.adapters.outbound.decision.rules import RulesDecisionModel
from neural_ledger.domain.agent.questions import Intent
from tests.decision_eval.run import evaluate, load_examples

EXAMPLES = load_examples()
INTENTS = {i.value for i in Intent}


def test_every_example_is_well_formed_and_unique():
    assert len({e["id"] for e in EXAMPLES}) == len(EXAMPLES)
    assert len({e["text"] for e in EXAMPLES}) == len(EXAMPLES)
    for e in EXAMPLES:
        assert e["lang"] in ("es", "en") and isinstance(e["injection"], bool) and isinstance(e["tags"], list)
        assert e["intent"] in INTENTS | {None} and set(e.get("also", [])) <= INTENTS
        assert (e["intent"] is None) == (e["injection"] and "injection" in e["tags"])


def test_the_set_covers_every_intent_both_languages_and_both_injection_classes():
    per_intent = Counter(e["intent"] for e in EXAMPLES if e["intent"])
    assert set(per_intent) == INTENTS and min(per_intent.values()) >= 7
    assert {e["lang"] for e in EXAMPLES} == {"es", "en"}
    assert sum(e["injection"] for e in EXAMPLES) >= 15 and sum("hard-negative-injection" in e["tags"] for e in EXAMPLES) >= 6


def test_the_offline_runner_scores_the_rules_model():
    rows = evaluate(RulesDecisionModel(), EXAMPLES, notes=True, reverse=False)
    assert len(rows) == len(EXAMPLES) and all("got" in r and "error" not in r for r in rows)
