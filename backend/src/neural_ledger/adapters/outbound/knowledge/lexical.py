"""KnowledgeBase on BM25 over the concept cards, standard library only (ADR-039). The offline default and the fallback.

Each card is one bag of words: title and aliases count three times (they are what people type), then tags and body.
Words are case- and accent-folded ("Interés" = "interes"), Spanish and English stopwords and question words
("qué", "what", "explica") are dropped, and every word is cut to its first five letters, a crude stemmer that works
for both languages at once: "intereses" and "interés" meet at "inter", "créditos" and "credit" at "credi".

Scores are absolute, not relative to the best card. A raw BM25 score is divided by the score an average-length card
would get with every query word appearing once, then capped at 1. So the score says how much of the question the
card covers: an unrelated question scores near 0 even when it is the "best" match, and the use case's `min_score`
means the same thing for every question. Words the corpus never uses count at the highest weight in that ceiling,
so "what is the weather in Paris" stays low because of the words no card has.

Cards in the asked language come first; when none of them matches, the other language answers.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence

from ....domain.education.concepts import LANGUAGES, ConceptCard, Passage
from .corpus_loader import corpus_hash

K1 = 1.2
B = 0.75
TITLE_WEIGHT = 3  # title and each alias
STEM = 5  # letters kept per word

_STOPWORDS = frozenset(
    """
    a al algo como con cual cuales de del el ella ellos en entre era es esa ese eso esta este esto estos fue ha hay
    la las le les lo los mas me mi mis muy no nos o para pero por porque que se si sin sobre son su sus te tiene tu
    tus un una uno unos y ya yo
    explica explicame explicar significa significado define definicion concepto quiero saber decir dime funciona
    sirve entender entiendo
    an and are as at be by can could do does for from how i in is it its me my of on or so that the their them this
    to was what when where which who why will with you your
    explain meaning mean means define definition concept tell know understand work works
    """.split()
)


def tokens(text: str) -> list[str]:
    """Folded, stopword-free, stemmed words."""
    folded = "".join(ch for ch in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(ch))
    return [w[:STEM] for w in re.findall(r"[a-z0-9]+", folded) if w not in _STOPWORDS]


class LexicalKnowledgeBase:
    def __init__(self, cards: Sequence[ConceptCard]) -> None:
        self._cards = tuple(cards)
        self.name = f"lexical/{corpus_hash(self._cards)[:8]}"
        self._bags = [Counter(_card_words(c)) for c in self._cards]
        self._lengths = [sum(bag.values()) for bag in self._bags]
        self._avg_length = (sum(self._lengths) / len(self._lengths)) if self._lengths else 1.0
        n = len(self._cards)
        df = Counter(word for bag in self._bags for word in bag)
        self._idf = {word: _idf(n, count) for word, count in df.items()}
        self._unseen_idf = _idf(n, 0)

    def search(self, query: str, lang: str, k: int) -> Sequence[Passage]:
        words = set(tokens(query))
        if not words or k <= 0:
            return ()
        ceiling = sum(self._idf.get(w, self._unseen_idf) for w in words)
        scored = [(self._bm25(i, words), i) for i in range(len(self._cards))]
        matches = [(raw, i) for raw, i in scored if raw > 0]
        if lang in LANGUAGES:
            preferred = [(raw, i) for raw, i in matches if self._cards[i].lang == lang]
            matches = preferred or matches
        # Rank by the raw score: several cards can reach the capped score of 1 and must still come out best first.
        matches.sort(key=lambda m: (-m[0], self._cards[m[1]].id))
        return tuple(Passage(self._cards[i], self._cards[i].body, min(1.0, raw / ceiling)) for raw, i in matches[:k])

    def _bm25(self, i: int, words: set[str]) -> float:
        bag, norm = self._bags[i], K1 * (1 - B + B * self._lengths[i] / self._avg_length)
        return sum(self._idf[w] * bag[w] * (K1 + 1) / (bag[w] + norm) for w in words if bag[w])


def _card_words(card: ConceptCard) -> list[str]:
    heading = tokens(" ".join((card.title, *card.aliases)))
    return heading * TITLE_WEIGHT + tokens(" ".join(card.tags)) + tokens(card.body)


def _idf(n: int, df: int) -> float:
    """BM25+ style idf, always positive (a word in every card still counts a little)."""
    return math.log(1 + (n - df + 0.5) / (df + 0.5))
