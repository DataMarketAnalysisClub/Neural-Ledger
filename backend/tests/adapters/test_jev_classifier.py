"""Jev as the transaction classifier (ADR-032): one question per distinct text, cached, fails as one."""

from __future__ import annotations

import threading

import pytest

from neural_ledger.adapters.outbound.classifier.jev import MAX_TEXT, JevTransactionClassifier
from neural_ledger.adapters.outbound.decision.jev import JevDecisionModel
from neural_ledger.application.ports import ClassifierUnavailable, DecisionModelUnavailable, TransactionClassifier
from neural_ledger.domain.agent.questions import Judgment
from neural_ledger.domain.ledger.categorization import CATEGORY_QUESTION, CategoryGuess
from tests.adapters.test_openai_compatible_adapters import FakeServer

SECRET = "test_secret_value_not_a_real_key"


class FakeJev:
    """A DecisionModel that answers from a table and records every state it was asked about."""

    name = "jev:jev-1.14-20261014"

    def __init__(self, answers: dict[str, tuple[str, float]] | None = None, down_on: str | None = None) -> None:
        self.answers = answers or {}
        self.down_on = down_on
        self.asked: list[str] = []
        self._lock = threading.Lock()

    def judge(self, state, questions):
        with self._lock:
            self.asked.append(state)
        assert questions == (CATEGORY_QUESTION,)
        if state == self.down_on:
            raise DecisionModelUnavailable("jev returned HTTP 503: overloaded")
        label, confidence = self.answers.get(state, ("other", 0.3))
        return {"category": Judgment("category", label, ((label, confidence),), confidence, "jev:jev-1.14-20261014")}


def test_is_a_transaction_classifier_named_after_the_model():
    classifier = JevTransactionClassifier(FakeJev())
    assert isinstance(classifier, TransactionClassifier) and classifier.name == "jev:jev-1.14-20261014"


def test_one_question_per_distinct_text_answers_in_order_with_the_source():
    jev = FakeJev({"UBER TRIP": ("transport", 0.93), "LIDER": ("groceries", 0.88)})
    guesses = JevTransactionClassifier(jev).classify(["UBER TRIP", "LIDER", "UBER TRIP", "  UBER   TRIP "])
    assert guesses == (
        CategoryGuess("transport", 0.93, "jev:jev-1.14-20261014"),
        CategoryGuess("groceries", 0.88, "jev:jev-1.14-20261014"),
        CategoryGuess("transport", 0.93, "jev:jev-1.14-20261014"),
        CategoryGuess("transport", 0.93, "jev:jev-1.14-20261014"),  # whitespace does not make a new merchant
    )
    assert sorted(jev.asked) == ["LIDER", "UBER TRIP"]


def test_answers_are_cached_so_a_reimport_asks_only_for_new_text():
    jev = FakeJev()
    classifier = JevTransactionClassifier(jev)
    classifier.classify(["A", "B"])
    classifier.classify(["B", "C", "A"])
    assert sorted(jev.asked) == ["A", "B", "C"]


def test_cache_is_bounded():
    jev = FakeJev()
    classifier = JevTransactionClassifier(jev, cache_size=2)
    classifier.classify(["A", "B", "C"])
    classifier.classify(["A"])  # evicted: asked again
    assert jev.asked.count("A") == 2


def test_no_lines_no_questions():
    jev = FakeJev()
    assert JevTransactionClassifier(jev).classify([]) == ()
    assert jev.asked == []


def test_long_text_is_cut_before_it_is_sent():
    jev = FakeJev()
    JevTransactionClassifier(jev).classify(["X" * 5_000])
    assert jev.asked == ["X" * MAX_TEXT]


def test_one_unavailable_answer_fails_the_whole_batch_so_the_fallback_answers_all_of_it():
    jev = FakeJev(down_on="B")
    with pytest.raises(ClassifierUnavailable, match="503"):
        JevTransactionClassifier(jev).classify(["A", "B", "C"])


def test_an_unusable_answer_is_unavailable_too():
    class Broken(FakeJev):
        def judge(self, state, questions):
            return {}  # no 'category' key

    with pytest.raises(ClassifierUnavailable, match="unusable"):
        JevTransactionClassifier(Broken()).classify(["A"])


# ---- over the wire, against a local fake System One server -------------------------------------------------


@pytest.fixture
def server():
    body = {
        "model": "jev-1.14-20261014",
        "answers": {
            "category": {
                "type": "choice",
                "choice": "dining",
                "probabilities": {o: (0.9 if o == "dining" else round(0.1 / 7, 6)) for o in CATEGORY_QUESTION.options},
                "confidence": 0.84,
            }
        },
    }
    fake = FakeServer(body=body)
    yield fake
    fake.close()


def test_wire_format_sends_the_category_question_and_the_text_as_state(server):
    model = JevDecisionModel(SECRET, "jev-1.14-20261014", base_url=server.url)
    (guess,) = JevTransactionClassifier(model).classify(["Compra Nacional VD STARBUCKS COFFEE CENTRO"])
    assert guess == CategoryGuess("dining", 0.84, "jev:jev-1.14-20261014")
    (request,) = server.requests
    assert request["headers"]["Authorization"] == f"Bearer {SECRET}"
    sent = request["body"]
    assert sent["state"] == "Compra Nacional VD STARBUCKS COFFEE CENTRO"
    assert list(sent["questions"]) == ["category"]
    question = sent["questions"]["category"]
    assert question["type"] == "choice" and question["criteria"] == dict(zip(CATEGORY_QUESTION.options, CATEGORY_QUESTION.notes))


def test_http_error_becomes_classifier_unavailable_without_the_key():
    fake = FakeServer(status=401, body={"error": "invalid key"})
    try:
        with pytest.raises(ClassifierUnavailable) as caught:
            JevTransactionClassifier(JevDecisionModel(SECRET, base_url=fake.url)).classify(["LIDER"])
        assert "401" in str(caught.value) and SECRET not in str(caught.value)
    finally:
        fake.close()


def test_without_a_key_it_is_unavailable_before_any_request():
    with pytest.raises(ClassifierUnavailable, match="no API key"):
        JevTransactionClassifier(JevDecisionModel(None)).classify(["LIDER"])
