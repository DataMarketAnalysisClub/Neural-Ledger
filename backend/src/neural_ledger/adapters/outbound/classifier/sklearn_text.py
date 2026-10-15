"""TransactionClassifier on scikit-learn (the `ml` extra), adapted from ocr_tabular's ml/ ExpenditureClassifier.

The method is a pipeline factory. `naive_bayes` is the original: TF-IDF over character n-grams
(robust to Spanish brand names and OCR noise) into MultinomialNB. To try another method, pass
another factory returning any scikit-learn estimator with `predict_proba`, or write another
TransactionClassifier adapter and register it in bootstrap/container.py.

The model is trained at first use from training/categories.csv and never pickled, so it is
rebuilt from versioned code and data. Its `name` carries the training data's hash: every
posted transaction records which model and which data chose its category.

The training rows go through the same redaction rules as imported lines (ADR-028), so the model
learns from what it will see ("TRANSFERENCIA A TERCEROS [PERSON]"), never from raw names or numbers.
The rules' version is part of the hash, so a rules change also renames the model.

training/categories.csv is ocr_tabular's synthetic example set (Chilean merchants), with labels
mapped to the ledger vocabulary (Supermercado -> groceries, ...) and the income rows dropped,
because income is decided by the amount's sign.
"""

from __future__ import annotations

import csv
import hashlib
import re
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ....application.ports import ClassifierUnavailable
from ....domain.ledger.categorization import CategoryGuess
from ....domain.privacy.redaction import REDACTION_VERSION, redact_text

TRAINING_DATA = Path(__file__).with_name("training") / "categories.csv"

# Words a bank prints around the merchant. Left in, they decide the class: the training rows say
# 'COMPRA TDB JUMBO' and a cartola says 'Compra Nacional MD <anything>', so every purchase looked
# like groceries at 0.8. Transfer words stay: they are the signal for 'other'.
_BOILERPLATE = frozenset(
    {
        "compra",
        "compras",
        "nacional",
        "internacional",
        "md",
        "tdb",
        "pago",
        "pagos",
        "en",
        "linea",
        "cargo",
        "automatico",
        "mensual",
        "recurrentes",
    }
)


def normalize(text: str) -> str:
    """Lowercase, keep letters only, drop bank boilerplate."""
    words = re.sub(r"[^a-záéíóúüñ]+", " ", str(text).lower()).split()
    return " ".join(w for w in words if w not in _BOILERPLATE)


def naive_bayes() -> Any:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.naive_bayes import MultinomialNB
    from sklearn.pipeline import make_pipeline

    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), max_features=5000, sublinear_tf=True)
    return make_pipeline(vectorizer, MultinomialNB(alpha=0.5))


class SklearnTextClassifier:
    def __init__(
        self, make_model: Callable[[], Any] = naive_bayes, *, method: str = "naive_bayes", training_data: Path = TRAINING_DATA
    ) -> None:
        self._make_model = make_model
        self._training_data = training_data
        self.name = f"{method}@{hashlib.sha256(training_data.read_bytes() + REDACTION_VERSION.encode()).hexdigest()[:12]}"
        self._model: Any = None
        self._lock = threading.Lock()

    def classify(self, descriptions: Sequence[str]) -> tuple[CategoryGuess, ...]:
        if not descriptions:
            return ()
        model = self._trained()
        probabilities = model.predict_proba([normalize(d) for d in descriptions])
        guesses = []
        for row in probabilities:
            best = int(row.argmax())
            guesses.append(CategoryGuess(str(model.classes_[best]), float(row[best])))
        return tuple(guesses)

    def _trained(self) -> Any:
        with self._lock:
            if self._model is None:
                try:
                    model = self._make_model()
                except ImportError as exc:
                    raise ClassifierUnavailable("transaction categories need the `ml` extra (pip install 'neural-ledger[ml]')") from exc
                texts, labels = self._examples()
                model.fit(texts, labels)
                self._model = model
            return self._model

    def _examples(self) -> tuple[list[str], list[str]]:
        with self._training_data.open(encoding="utf-8", newline="") as f:
            rows = [(normalize(redact_text(r["description"])), r["category"].strip()) for r in csv.DictReader(f)]
        rows = [(text, label) for text, label in rows if text and label]
        if len({label for _, label in rows}) < 2:
            raise ClassifierUnavailable(f"{self._training_data.name} needs examples of at least two categories")
        return [t for t, _ in rows], [label for _, label in rows]
