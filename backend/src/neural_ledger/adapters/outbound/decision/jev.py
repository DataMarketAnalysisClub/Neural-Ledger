"""TypeSafe Jev adapter (Role B; go/no-go Oct 14).

Jev is a "System One" model: it answers closed questions with typed, calibrated results.
Endpoint: POST {base_url}/v1/systemone, Bearer key, body {"state": <text>, "model": "jev-latest",
"questions": {<id>: {...}}}. All questions of one call are evaluated independently against the same state,
so one request answers intent and injection together. Two hosts implement the same protocol:
- OpenRouter (https://openrouter.ai/docs/guides/community/typesafe-sdk): base https://openrouter.ai/api,
  Bearer OPENROUTER_API_KEY. This is the default path (D-02: OpenRouter is the one provider).
- TypeSafe direct (https://docs.typesafe.ai/api): base https://api.typesafe.ai, Bearer TYPESAFE_API_KEY.

Mapping:   ChoiceQuestion -> choice  (criteria: option -> note)   answer: choice, probabilities, confidence
           ScoreQuestion  -> score   (criteria: ordered levels)   answer: score, probabilities "0".."n", confidence
           YesNoQuestion  -> noul                                 answer: noul in 0..1 (no confidence field)

A Noul has no confidence of its own, so its confidence is max(p, 1 - p), the same convention as the rules
model. `jev-latest` is an alias that moves when a new release ships; the answering version is reported in
`Judgment.source` ("jev:jev-1.13.0") so audit records show which model decided.

Security notes:
- The user's text goes in `state`, which Jev treats as data, but its docs warn that text arguing for its own
  classification can move an answer. Jev's output is advisory: the injection flag only restricts, and the
  gate, the permissions and the verifier stay deterministic.
- Any network, HTTP or malformed-response error raises DecisionModelUnavailable, so the chain falls through
  to the next model (rules), which is the designed behaviour for "Jev down" (test S10). The API key only
  travels in the Authorization header and is never put in an error message.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any

from ....application.ports import DecisionModelUnavailable
from ....domain.agent.questions import ChoiceQuestion, Judgment, Question, ScoreQuestion, YesNoQuestion

USER_AGENT = "neural-ledger/0.1"
TYPESAFE_BASE_URL = "https://api.typesafe.ai"
OPENROUTER_BASE_URL = "https://openrouter.ai/api"


class JevDecisionModel:
    def __init__(self, api_key: str | None, model: str = "jev-latest", base_url: str = TYPESAFE_BASE_URL, timeout_s: float = 5.0) -> None:
        self.name = f"jev:{model}"
        self._api_key = api_key
        self._model = model
        self._url = base_url.rstrip("/") + "/v1/systemone"
        self._timeout_s = timeout_s

    @property
    def endpoint(self) -> str:
        return self._url

    def judge(self, state: str, questions: Sequence[Question]) -> Mapping[str, Judgment]:
        if not self._api_key:
            raise DecisionModelUnavailable("no API key is set for jev (OPENROUTER_API_KEY or TYPESAFE_API_KEY)")
        body = {"state": state, "model": self._model, "questions": {q.key: _question(q) for q in questions}}
        request = urllib.request.Request(
            self._url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json", "User-Agent": USER_AGENT},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise DecisionModelUnavailable(f"jev returned HTTP {exc.code}: {_error_detail(exc)}") from exc
        except (OSError, json.JSONDecodeError) as exc:  # URLError and timeouts are OSError
            raise DecisionModelUnavailable(f"jev request failed: {exc}") from exc
        try:
            source = f"jev:{data.get('model') or self._model}"
            answers = data["answers"]
            return {q.key: _judgment(q, answers[q.key], source) for q in questions}
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
            raise DecisionModelUnavailable(f"jev returned an unexpected response: {exc!r}") from exc


def _question(q: Question) -> dict[str, Any]:
    if isinstance(q, ChoiceQuestion):
        notes = q.notes if len(q.notes) == len(q.options) else (None,) * len(q.options)
        return {"type": "choice", "instructions": q.prompt, "criteria": dict(zip(q.options, notes, strict=True))}
    if isinstance(q, ScoreQuestion):
        return {"type": "score", "instructions": q.prompt, "criteria": list(q.scale)}
    return {"type": "noul", "instructions": q.prompt}


def _judgment(q: Question, answer: Mapping[str, Any], source: str) -> Judgment:
    if answer["type"] != _question(q)["type"]:
        raise ValueError(f"answer type {answer['type']!r} for question {q.key!r}")
    if isinstance(q, YesNoQuestion):
        p_yes = _probability(answer["noul"])
        return Judgment(q.key, "yes" if p_yes >= 0.5 else "no", (("yes", p_yes), ("no", round(1 - p_yes, 6))), max(p_yes, 1 - p_yes), source)
    if isinstance(q, ChoiceQuestion):
        labels, raw = q.options, answer["probabilities"]
        probabilities = tuple((label, _probability(raw[label])) for label in labels)
        chosen = answer["choice"]
        if chosen not in labels:
            raise ValueError(f"choice {chosen!r} is not an option of {q.key!r}")
    else:
        labels = q.scale
        probabilities = tuple((label, _probability(answer["probabilities"][str(i)])) for i, label in enumerate(labels))
        chosen = max(probabilities, key=lambda pair: pair[1])[0]
    return Judgment(q.key, chosen, probabilities, _probability(answer["confidence"]), source)


def _probability(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0.0 <= value <= 1.0:
        raise ValueError(f"not a probability: {value!r}")
    return float(value)


def _error_detail(exc: urllib.error.HTTPError) -> str:
    """The provider's error body (truncated), so a silent fallback can be diagnosed. It never contains the request key."""
    try:
        return exc.read(300).decode("utf-8", errors="replace").strip() or str(exc.reason)
    except OSError:
        return str(exc.reason)
