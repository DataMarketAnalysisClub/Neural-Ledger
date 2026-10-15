"""The naive Bayes transaction classifier (ml extra): trained from versioned data, swappable, honest about doubt."""

from __future__ import annotations

import csv
import sys

import pytest

from neural_ledger.adapters.outbound.classifier.sklearn_text import TRAINING_DATA, SklearnTextClassifier, normalize
from neural_ledger.application.ports import ClassifierUnavailable, TransactionClassifier
from neural_ledger.domain.ledger.categorization import CATEGORIES, MIN_CATEGORY_CONFIDENCE

pytest.importorskip("sklearn")


@pytest.fixture(scope="module")
def classifier() -> SklearnTextClassifier:
    return SklearnTextClassifier()


def test_is_a_transaction_classifier_named_after_its_method_and_data(classifier):
    assert isinstance(classifier, TransactionClassifier)
    method, data_hash = classifier.name.split("@")
    assert method == "naive_bayes" and len(data_hash) == 12


def test_training_labels_are_the_ledger_vocabulary():
    with TRAINING_DATA.open(encoding="utf-8") as f:
        labels = {row["category"] for row in csv.DictReader(f)}
    assert labels <= CATEGORIES


@pytest.mark.parametrize(
    ("description", "category"),
    [
        ("Compra Nacional MD HIP LIDER P", "groceries"),
        ("COMPRA TDB UNIMARC", "groceries"),
        ("Compra Nacional MD FARMACIAS AHUMADA", "health"),
        ("Compra Nacional MD COPEC", "transport"),
        ("Pagos Recurrentes MD NETFLIX", "entertainment"),
    ],
)
def test_known_merchants_are_confident(classifier, description, category):
    (guess,) = classifier.classify([description])
    assert guess.category == category and guess.confidence >= MIN_CATEGORY_CONFIDENCE


def test_bank_boilerplate_does_not_decide_the_category(classifier):
    # Before boilerplate removal every 'Compra Nacional MD <unknown>' came back groceries at ~0.8.
    assert normalize("Compra Nacional MD ZXQW KLMN") == "zxqw klmn"
    (guess,) = classifier.classify(["Compra Nacional MD ZXQW KLMN"])
    assert guess.confidence < MIN_CATEGORY_CONFIDENCE


def test_one_guess_per_description_in_order_and_deterministic(classifier):
    texts = ["COMPRA TDB UNIMARC", "", "Compra Nacional MD COPEC"]
    guesses = classifier.classify(texts)
    assert len(guesses) == 3 and guesses[0].category == "groceries" and guesses[2].category == "transport"
    assert SklearnTextClassifier().classify(texts) == guesses
    assert classifier.classify([]) == ()


def test_the_method_is_swappable_by_factory(tmp_path):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline

    other = SklearnTextClassifier(
        lambda: make_pipeline(TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5)), LogisticRegression()), method="logreg"
    )
    assert other.name.startswith("logreg@")
    assert other.classify(["COMPRA TDB UNIMARC"])[0].category == "groceries"


def test_the_name_changes_with_the_training_data(tmp_path):
    data = tmp_path / "categories.csv"
    data.write_text("description,category\nJUMBO,groceries\nCOPEC,transport\n", encoding="utf-8")
    assert SklearnTextClassifier(training_data=data).name != SklearnTextClassifier().name


def test_training_rows_go_through_the_same_redaction_rules_as_imported_lines(tmp_path):
    # Fictional data: the model learns 'transf a person id', exactly what an imported line looks like after redaction.
    data = tmp_path / "categories.csv"
    data.write_text("description,category\nTRANSF A JUAN PEREZ 11.111.111-1,other\nJUMBO 401,groceries\n", encoding="utf-8")
    assert SklearnTextClassifier(training_data=data)._examples() == (["transf a person id", "jumbo"], ["other", "groceries"])
    shipped, _ = SklearnTextClassifier()._examples()
    assert "transferencia a terceros person" in shipped and not any("juan" in text for text in shipped)


def test_the_name_changes_with_the_redaction_rules(monkeypatch):
    from neural_ledger.adapters.outbound.classifier import sklearn_text

    before = SklearnTextClassifier().name
    monkeypatch.setattr(sklearn_text, "REDACTION_VERSION", "pii-next")
    assert SklearnTextClassifier().name != before


def test_training_data_with_one_category_is_unavailable(tmp_path):
    data = tmp_path / "categories.csv"
    data.write_text("description,category\nJUMBO,groceries\n", encoding="utf-8")
    with pytest.raises(ClassifierUnavailable, match="two categories"):
        SklearnTextClassifier(training_data=data).classify(["JUMBO"])


def test_missing_ml_extra_is_unavailable_not_a_crash(monkeypatch):
    monkeypatch.setitem(sys.modules, "sklearn.naive_bayes", None)
    with pytest.raises(ClassifierUnavailable, match="ml"):
        SklearnTextClassifier().classify(["JUMBO"])
