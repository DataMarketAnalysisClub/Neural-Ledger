"""Deterministic decision model (keywords). Always available, no network: the floor of the chain.

Answers the standard closed questions (intent, injection, risk tolerance). Anything else raises
DecisionModelUnavailable so the chain can try another model or fail closed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ....application.ports import DecisionModelUnavailable
from ....domain.agent.questions import (
    ChoiceQuestion,
    Intent,
    Judgment,
    Question,
    ScoreQuestion,
    YesNoQuestion,
)
from ..text.lexicon import INJECTION_PATTERNS, INTENT_PATTERNS, TOLERANCE_PATTERNS


def _spread(label: str, confidence: float, options: Sequence[str]) -> tuple[tuple[str, float], ...]:
    others = [o for o in options if o != label]
    rest = round((1 - confidence) / len(others), 4) if others else 0.0
    return tuple((o, confidence if o == label else rest) for o in options)


class RulesDecisionModel:
    name = "rules-0.1"

    def judge(self, state: str, questions: Sequence[Question]) -> Mapping[str, Judgment]:
        answers: dict[str, Judgment] = {}
        for q in questions:
            if isinstance(q, ChoiceQuestion) and q.key == "intent":
                answers[q.key] = self._intent(state, q)
            elif isinstance(q, YesNoQuestion) and q.key == "injection":
                answers[q.key] = self._injection(state)
            elif isinstance(q, ScoreQuestion) and q.key == "risk_tolerance":
                answers[q.key] = self._tolerance(state, q)
            else:
                raise DecisionModelUnavailable(f"rules model cannot answer {q.key!r}")
        return answers

    def _intent(self, text: str, q: ChoiceQuestion) -> Judgment:
        matched = [intent for intent, pattern in INTENT_PATTERNS if pattern.search(text)]
        if not matched:
            label, confidence = Intent.SMALLTALK.value, 0.5
        else:
            label, confidence = matched[0].value, 0.92 if len(matched) == 1 else 0.85
        return Judgment("intent", label, _spread(label, confidence, q.options), confidence, self.name)

    def _injection(self, text: str) -> Judgment:
        hit = any(p.search(text) for p in INJECTION_PATTERNS)
        p_yes = 0.95 if hit else 0.03
        label = "yes" if hit else "no"
        return Judgment("injection", label, (("yes", p_yes), ("no", round(1 - p_yes, 4))), max(p_yes, 1 - p_yes), self.name)

    def _tolerance(self, text: str, q: ScoreQuestion) -> Judgment:
        for label, pattern in TOLERANCE_PATTERNS:
            if pattern.search(text):
                return Judgment("risk_tolerance", label, _spread(label, 0.85, q.scale), 0.85, self.name)
        return Judgment("risk_tolerance", "moderate", _spread("moderate", 0.34, q.scale), 0.34, self.name)
