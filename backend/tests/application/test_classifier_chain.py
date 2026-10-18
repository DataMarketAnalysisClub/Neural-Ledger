"""Jev first, naive Bayes as the fallback (ADR-032): who answers, what each transaction records, offline floor."""

from __future__ import annotations

from datetime import date

import pytest

from neural_ledger.adapters.outbound.classifier.jev import JevTransactionClassifier
from neural_ledger.adapters.outbound.statements.synthetic import SyntheticStatements
from neural_ledger.application.ports import ClassifierUnavailable
from neural_ledger.application.services.classifier_fallback import FallbackClassifier
from neural_ledger.bootstrap import container
from neural_ledger.bootstrap.config import Settings
from neural_ledger.bootstrap.container import build
from neural_ledger.domain.ledger.categorization import CategoryGuess
from tests.adapters.test_jev_classifier import FakeJev
from tests.conftest import make_settings


class Fixed:
    def __init__(self, name: str, category: str = "shopping", down: bool = False) -> None:
        self.name, self.category, self.down, self.calls = name, category, down, 0

    def classify(self, descriptions):
        self.calls += 1
        if self.down:
            raise ClassifierUnavailable(f"{self.name} is down")
        return tuple(CategoryGuess(self.category, 0.9) for _ in descriptions)


class AllDining(FakeJev):
    def judge(self, state, questions):
        self.answers[state] = ("dining", 0.9)
        return super().judge(state, questions)


# ---- FallbackClassifier --------------------------------------------------------------------------------------


def test_the_first_classifier_that_answers_answers_everything_and_is_the_source():
    first, second = Fixed("jev:x", "dining"), Fixed("nb@y", "groceries")
    chain = FallbackClassifier([first, second])
    assert chain.name == "jev:x+nb@y"
    assert chain.classify(["a", "b"]) == (CategoryGuess("dining", 0.9, "jev:x"),) * 2
    assert second.calls == 0


def test_an_unavailable_classifier_falls_through_to_the_next(caplog):
    chain = FallbackClassifier([Fixed("jev:x", down=True), Fixed("nb@y", "groceries")])
    assert chain.classify(["a"]) == (CategoryGuess("groceries", 0.9, "nb@y"),)
    assert "jev:x unavailable" in caplog.text  # a silent fallback would look like a working Jev


def test_all_unavailable_is_unavailable():
    with pytest.raises(ClassifierUnavailable, match="all classifiers failed"):
        FallbackClassifier([Fixed("a", down=True), Fixed("b", down=True)]).classify(["x"])


def test_a_guess_that_names_its_own_source_keeps_it():
    class Sourced(Fixed):
        def classify(self, descriptions):
            return tuple(CategoryGuess("dining", 0.9, "jev:jev-1.13.0") for _ in descriptions)

    assert FallbackClassifier([Sourced("jev:jev-latest")]).classify(["x"])[0].source == "jev:jev-1.13.0"


def test_an_empty_chain_is_a_configuration_error():
    with pytest.raises(ValueError):
        FallbackClassifier([])


# ---- configuration and wiring --------------------------------------------------------------------------------


def test_jev_in_the_chain_is_live_mode_and_naive_bayes_alone_is_offline():
    assert Settings.from_env({}).mode == "offline"
    assert Settings.from_env({"NL_CLASSIFIER": "jev,naive_bayes"}).mode == "live"
    # The Azure detector receives raw statement text before redaction: that is live too (and needs the live keys).
    assert Settings.from_env({"NL_PII_DETECTOR": "azure"}).mode == "live"


def test_default_never_builds_jev():
    services, _ = build(make_settings())
    assert services.classifier.startswith("naive_bayes@") and "jev" not in services.classifier


def _import_cartola(services, user="camila"):
    (cartola,) = SyntheticStatements().checking(3, date(2026, 9, 1))
    return services.statements.import_statement(user, cartola.content)


def test_jev_answers_and_each_transaction_records_it(monkeypatch):
    monkeypatch.setitem(container.CLASSIFIERS, "jev", lambda s: JevTransactionClassifier(AllDining()))
    services, _ = build(make_settings(classifiers=("jev", "naive_bayes")))
    assert services.classifier.startswith("jev:jev-1.13.0+naive_bayes@")

    (imported,) = _import_cartola(services).data.imports
    assert imported.ledger.classifier == "jev:jev-1.13.0"  # only Jev answered
    transactions = services.ledger.list_transactions("camila").data.transactions
    charges = [t for t in transactions if t.amount < 0]
    assert charges and {t.classifier for t in charges} == {"jev:jev-1.13.0"} and {t.category for t in charges} == {"dining"}
    income = [t for t in transactions if t.amount > 0]
    assert income and {(t.category, t.classifier) for t in income} == {("income", "rule")}  # never asked


def test_jev_without_a_key_falls_back_to_naive_bayes_for_the_whole_statement():
    services, _ = build(make_settings(classifiers=("jev", "naive_bayes"), openrouter_api_key=None, typesafe_api_key=None))
    (imported,) = _import_cartola(services).data.imports
    assert imported.statement.verified and imported.ledger.posted == imported.statement.line_count
    assert imported.ledger.classifier.startswith("naive_bayes@")
    charges = [t for t in services.ledger.list_transactions("camila").data.transactions if t.amount < 0]
    assert {t.classifier.split("@")[0] for t in charges} == {"naive_bayes"}


def test_every_classifier_down_stores_the_statement_without_posting_it(monkeypatch):
    monkeypatch.setitem(container.CLASSIFIERS, "naive_bayes", lambda s: Fixed("nb@y", down=True))
    services, _ = build(make_settings(classifiers=("jev", "naive_bayes")))
    result = _import_cartola(services)
    (imported,) = result.data.imports
    assert imported.statement.verified and imported.ledger.posted == 0
    assert "NOT_POSTED" in [w.code for w in result.warnings]
    assert len(services.statements.list_statements("camila").data) == 1


def test_health_reports_the_classifier_chain():
    from fastapi.testclient import TestClient

    from neural_ledger.adapters.inbound.http.app import create_app

    services, _ = build(make_settings(classifiers=("jev", "naive_bayes")))
    body = TestClient(create_app(services)).get("/health").json()
    assert body["classifier"].startswith("jev:jev-1.13.0+naive_bayes@") and body["mode"] == "live"
