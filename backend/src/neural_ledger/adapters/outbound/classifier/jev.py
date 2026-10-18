"""TransactionClassifier on Jev (ADR-032): each distinct line text is one closed question.

The question is the domain's CATEGORY_QUESTION (the spending vocabulary with a note per option) and the
state is the line's text, already redacted at import (ADR-028): no name, RUT, account or card number is
in it. Jev's answer is a guess like any classifier's: post_statement keeps it only if it is in the
vocabulary with confidence >= 0.5, and income and card payments are never asked, they go by rule.

Cost and latency: a statement repeats merchants, so the texts are deduplicated and the distinct ones are
asked in parallel. Answers are cached for the life of the process, so re-importing or seeding the same
merchants asks again only for new text. The first failure (no key, network, HTTP or a malformed answer)
cancels the rest and raises ClassifierUnavailable, so a fallback classifier answers the whole statement.

Every guess carries the answering model ("jev:jev-1.14-20261014") as its source, recorded on the transaction.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Sequence
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait

from ....application.ports import ClassifierUnavailable, DecisionModel, DecisionModelUnavailable
from ....domain.ledger.categorization import CATEGORY_QUESTION, CategoryGuess

MAX_TEXT = 200  # a statement line is short; anything longer is not a merchant name


class JevTransactionClassifier:
    def __init__(self, model: DecisionModel, *, workers: int = 8, cache_size: int = 4096) -> None:
        self.name = model.name
        self._model = model
        self._workers = workers
        self._cache: OrderedDict[str, CategoryGuess] = OrderedDict()
        self._cache_size = cache_size
        self._lock = threading.Lock()

    def classify(self, descriptions: Sequence[str]) -> tuple[CategoryGuess, ...]:
        texts = [" ".join(str(d).split())[:MAX_TEXT] for d in descriptions]
        answers = {t: g for t in set(texts) if (g := self._cached(t)) is not None}
        pending = [t for t in dict.fromkeys(texts) if t not in answers]
        if pending:
            answers.update(self._ask_all(pending))
        return tuple(answers[t] for t in texts)

    def _ask_all(self, texts: list[str]) -> dict[str, CategoryGuess]:
        pool = ThreadPoolExecutor(max_workers=min(self._workers, len(texts)), thread_name_prefix="jev-category")
        try:
            futures = {pool.submit(self._ask, t): t for t in texts}
            done, _ = wait(futures, return_when=FIRST_EXCEPTION)
            failed = next((f for f in done if f.exception() is not None), None)
            if failed is not None:
                exc = failed.exception()
                if isinstance(exc, DecisionModelUnavailable):
                    raise ClassifierUnavailable(f"jev could not categorize: {exc}") from exc
                raise ClassifierUnavailable(f"jev returned an unusable category: {exc!r}") from exc
            answers = {futures[f]: f.result() for f in futures}
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        with self._lock:
            for text, guess in answers.items():
                self._cache[text] = guess
                self._cache.move_to_end(text)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return answers

    def _ask(self, text: str) -> CategoryGuess:
        judgment = self._model.judge(text, (CATEGORY_QUESTION,))[CATEGORY_QUESTION.key]
        return CategoryGuess(judgment.label, judgment.confidence, source=judgment.source)

    def _cached(self, text: str) -> CategoryGuess | None:
        with self._lock:
            guess = self._cache.get(text)
            if guess is not None:
                self._cache.move_to_end(text)
            return guess
