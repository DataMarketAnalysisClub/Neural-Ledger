"""The category set stays well formed and the naive Bayes baseline is pinned (no network, no key; ADR-032)."""

from __future__ import annotations

import csv
from collections import Counter

from neural_ledger.adapters.outbound.classifier.sklearn_text import TRAINING_DATA, SklearnTextClassifier, naive_bayes
from neural_ledger.domain.ledger.categorization import CATEGORIES, CategoryGuess
from neural_ledger.domain.privacy.redaction import redact_text
from tests.category_eval.run import load_examples, score

EXAMPLES = load_examples()


def test_every_example_is_well_formed_unique_and_already_redacted():
    assert len({e["text"] for e in EXAMPLES}) == len(EXAMPLES) >= 90
    for e in EXAMPLES:
        assert e["category"] in CATEGORIES and e["slice"] in ("seen", "unseen")
        assert redact_text(e["text"]) == e["text"], f"{e['text']!r} is not in the form the classifier receives"


def test_the_set_covers_every_category_and_both_slices():
    per_category = Counter(e["category"] for e in EXAMPLES)
    assert set(per_category) == CATEGORIES and min(per_category.values()) >= 6
    assert Counter(e["slice"] for e in EXAMPLES)["unseen"] >= 50


def test_unseen_merchants_are_really_absent_from_the_training_data():
    with TRAINING_DATA.open(encoding="utf-8", newline="") as f:
        trained = {word for row in csv.DictReader(f) for word in row["description"].upper().split()}
    generic = {"COMPRA", "COMPRAS", "PAGO", "LINEA", "CHILE", "MALL", "PLAZA", "CENTRO", "SUSCRIPCION"}
    for e in EXAMPLES:
        if e["slice"] == "unseen" and e["category"] != "other":
            words = [w for w in e["text"].removeprefix("Compra Nacional VD ").split() if len(w) >= 3 and w not in generic]
            assert any(w not in trained for w in words), f"every word of {e['text']!r} is in the training data: move it to 'seen'"


def test_score_counts_coverage_precision_and_wrong_accepted():
    examples = [{"text": "a", "category": "dining", "slice": "seen"}, {"text": "b", "category": "health", "slice": "unseen"}]
    report = score(examples, [CategoryGuess("dining", 0.9), CategoryGuess("dining", 0.8)])
    assert report["all"] == {"n": 2, "coverage": 1.0, "precision": 0.5, "wrong_accepted": 0.5}
    assert report["confusions"] == [{"expected": "health", "got": "dining", "count": 1}]
    assert score(examples, [CategoryGuess("dining", 0.4), CategoryGuess("health", 0.2)])["all"]["coverage"] == 0.0


def test_naive_bayes_baseline():
    """The bar Jev must clear (ADR-032): cover more unseen merchants without more wrong-but-accepted answers."""
    guesses = SklearnTextClassifier(naive_bayes, method="naive_bayes").classify([e["text"] for e in EXAMPLES])
    report = score(EXAMPLES, guesses)
    assert report["seen"]["coverage"] >= 0.75 and report["seen"]["wrong_accepted"] <= 0.03
    assert report["unseen"]["coverage"] <= 0.35  # the gap Jev is for
    assert report["all"]["wrong_accepted"] <= 0.05
