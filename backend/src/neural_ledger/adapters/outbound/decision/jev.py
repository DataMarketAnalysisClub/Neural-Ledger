"""TypeSafe Jev adapter (Role B, due Oct 13; go/no-go Oct 14).  NOT IMPLEMENTED YET.

Jev is a "System One" model: it answers closed questions with typed, calibrated results:
Choice (choice, probabilities, confidence), Score (score, probabilities, confidence) and
Noul (probability that a statement is true). Several questions can go in one call and are
evaluated independently; TypeSafe advises splitting multi-factor questions, which is what
our one-question-per-judgment port already does.

Mapping:   ChoiceQuestion -> Choice     ScoreQuestion -> Score     YesNoQuestion -> Noul
Endpoint (public docs): POST https://api.typesafe.ai/v1/systemone, Bearer TYPESAFE_API_KEY,
model "jev-latest" (pin "jev-1.13.0" for the demo). Also served without a waitlist through
Vercel AI Gateway (typesafe-ai/jev) and Cloudflare Workers AI (typesafe/jev).
Confirm the exact request/response field names in docs.typesafe.ai (Quick Start, Primitives,
Confidence) before implementing; do not guess them. Until then this adapter reports itself
unavailable and the chain falls through to the next model (rules), which is the designed
behaviour for "Jev down" (test S10).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ....application.ports import DecisionModelUnavailable
from ....domain.agent.questions import Judgment, Question


class JevDecisionModel:
    def __init__(self, api_key: str | None, model: str = "jev-latest", base_url: str = "https://api.typesafe.ai", timeout_s: float = 5.0) -> None:
        self.name = f"jev:{model}"
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def judge(self, state: str, questions: Sequence[Question]) -> Mapping[str, Judgment]:
        if not self._api_key:
            raise DecisionModelUnavailable("TYPESAFE_API_KEY is not set")
        raise DecisionModelUnavailable("Jev adapter not implemented yet (see module docstring)")
