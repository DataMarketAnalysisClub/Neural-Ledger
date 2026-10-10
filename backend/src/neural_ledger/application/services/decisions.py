"""Decision service: asks the configured decision models in order and gates the turn.

Chain order is configuration (e.g. "jev,rules"), not architecture. If every model is
unavailable, the turn fails closed into read-only mode (test S10).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ...domain.agent.policy import AgentPolicy, Gate, gate_for
from ...domain.agent.questions import (
    INJECTION_QUESTION,
    INTENT_QUESTION,
    Intent,
    Judgment,
    Question,
)
from ...domain.audit.events import DecisionCheck
from ..ports import DecisionModel, DecisionModelUnavailable


@dataclass(frozen=True, slots=True)
class DecisionOutcome:
    judgments: Mapping[str, Judgment]
    answered_by: str | None
    unavailable: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Classification:
    intent: Intent
    confidence: float
    gate: Gate
    injection_probability: float
    injection_flagged: bool
    answered_by: str | None
    checks: tuple[DecisionCheck, ...]


class DecisionService:
    def __init__(self, models: Sequence[DecisionModel], policy: AgentPolicy) -> None:
        self._models = tuple(models)
        self._policy = policy

    @property
    def chain(self) -> tuple[str, ...]:
        return tuple(m.name for m in self._models)

    def judge(self, state: str, questions: Sequence[Question]) -> DecisionOutcome:
        failures: list[str] = []
        for model in self._models:
            try:
                judgments = model.judge(state, questions)
            except DecisionModelUnavailable as exc:
                failures.append(f"{model.name}: {exc}")
                continue
            if all(q.key in judgments for q in questions):
                return DecisionOutcome(judgments, model.name, tuple(failures))
            failures.append(f"{model.name}: incomplete answer")
        return DecisionOutcome({}, None, tuple(failures))

    def classify(self, text: str) -> Classification:
        outcome = self.judge(text, (INTENT_QUESTION, INJECTION_QUESTION))
        if outcome.answered_by is None:
            return Classification(Intent.SMALLTALK, 0.0, Gate.READ_ONLY, 0.0, False, None, ())
        intent_j = outcome.judgments["intent"]
        injection_j = outcome.judgments["injection"]
        injection_p = injection_j.probability("yes")
        try:
            intent = Intent(intent_j.label)
        except ValueError:
            intent, confidence = Intent.SMALLTALK, 0.0
        else:
            confidence = intent_j.confidence
        checks = tuple(
            DecisionCheck(j.source, j.key, j.label, round(j.confidence, 4)) for j in (intent_j, injection_j)
        )
        return Classification(
            intent=intent,
            confidence=confidence,
            gate=gate_for(confidence, self._policy),
            injection_probability=injection_p,
            injection_flagged=injection_p >= self._policy.injection_threshold,
            answered_by=outcome.answered_by,
            checks=checks,
        )
