"""Every KnowledgeBase keeps the port's contract (ADR-039): up to k passages, best first, scores in [0, 1], the asked
language first, the other language when nothing in it matches, low scores for an unrelated question.

Small synthetic cards, not the real corpus (that is tests/unit/test_concept_cards.py and tests/rag_eval). Chroma runs
in memory with a deterministic bag-of-words embedder, so the test needs chromadb but no model download.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import pytest

from neural_ledger.adapters.outbound.knowledge.corpus_loader import corpus_hash, load_cards
from neural_ledger.adapters.outbound.knowledge.lexical import LexicalKnowledgeBase, tokens
from neural_ledger.application.ports import KnowledgeBaseUnavailable
from neural_ledger.application.services.knowledge_fallback import FallbackKnowledgeBase
from neural_ledger.domain.education.concepts import ConceptCard

CARDS = (
    ConceptCard("budget", "en", "Budget", "A budget is a plan that splits your monthly income between expenses and savings.", aliases=("spending plan",)),
    ConceptCard("budget", "es", "Presupuesto", "Un presupuesto es un plan que reparte tu ingreso mensual entre gastos y ahorro.", aliases=("budget",)),
    ConceptCard("interest_rate", "en", "Interest rate", "The interest rate is the yearly price of borrowed money, charged by a lender."),
    ConceptCard(
        "interest_rate", "es", "Tasa de interés", "La tasa de interés es el precio anual del dinero prestado que cobra un banco.", aliases=("interest rate",)
    ),
    ConceptCard("etf", "en", "Exchange-traded fund", "An ETF is a fund whose shares trade on a stock exchange like a single stock.", aliases=("etf",)),
)

_DIMENSIONS = 4096


def fake_embedding(texts):
    """Bag of stemmed words hashed into 4,096 dimensions; a text with no words points along its own axis."""
    vectors = []
    for text in texts:
        vector = [0.0] * (_DIMENSIONS + 1)
        for word in tokens(text):
            vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % _DIMENSIONS] += 1.0
        if not any(vector):
            vector[_DIMENSIONS] = 1.0
        norm = math.sqrt(sum(v * v for v in vector))
        vectors.append([v / norm for v in vector])
    return vectors


def _lexical(cards):
    return LexicalKnowledgeBase(cards)


def _chroma(cards):
    pytest.importorskip("chromadb")
    from neural_ledger.adapters.outbound.knowledge.chroma import ChromaKnowledgeBase

    return ChromaKnowledgeBase(cards, None, "fake-bow", embedding_function=fake_embedding)


@pytest.fixture(params=[_lexical, _chroma], ids=["lexical", "chroma"])
def make(request):
    return request.param


def test_returns_at_most_k_passages_best_first_with_scores_in_unit_range(make):
    kb = make(CARDS)
    passages = kb.search("monthly budget plan for income and expenses", "en", 2)
    assert 1 <= len(passages) <= 2
    assert passages[0].card.id == "budget"
    assert all(0.0 <= p.score <= 1.0 for p in passages)
    assert [p.score for p in passages] == sorted((p.score for p in passages), reverse=True)
    assert passages[0].text == passages[0].card.body


def test_prefers_cards_in_the_asked_language(make):
    kb = make(CARDS)
    assert [(p.card.id, p.card.lang) for p in kb.search("interest rate", "es", 1)] == [("interest_rate", "es")]
    assert [(p.card.id, p.card.lang) for p in kb.search("interest rate", "en", 1)] == [("interest_rate", "en")]


def test_falls_back_to_the_other_language_when_nothing_matches(make):
    kb = make(CARDS)
    passages = kb.search("ETF fund shares stock exchange", "es", 3)
    assert passages and passages[0].card.id == "etf" and passages[0].card.lang == "en"


def test_an_unrelated_question_scores_low(make):
    kb = make(CARDS)
    related = kb.search("what is a budget", "en", 1)[0].score
    unrelated = kb.search("weather forecast tomorrow Paris", "en", 3)
    assert all(p.score < 0.2 for p in unrelated)
    assert related > 0.5


def test_the_name_changes_when_the_corpus_changes(make):
    edited = (*CARDS[:-1], ConceptCard("etf", "en", "Exchange-traded fund", CARDS[-1].body + " Edited."))
    assert make(CARDS).name != make(edited).name
    assert make(CARDS).name.endswith(corpus_hash(CARDS)[:8])


class _Down:
    name = "down/1"

    def search(self, query, lang, k):
        raise KnowledgeBaseUnavailable("no index")


def test_the_fallback_answers_from_the_next_index_and_names_the_chain():
    lexical = LexicalKnowledgeBase(CARDS)
    chain = FallbackKnowledgeBase([_Down(), lexical])
    assert chain.name == f"down/1+{lexical.name}"
    assert [p.card.id for p in chain.search("budget", "en", 1)] == ["budget"]


def test_the_fallback_raises_when_every_index_is_down():
    with pytest.raises(KnowledgeBaseUnavailable):
        FallbackKnowledgeBase([_Down(), _Down()]).search("budget", "en", 1)
    with pytest.raises(ValueError):
        FallbackKnowledgeBase([])


def test_chroma_turns_a_broken_embedder_into_unavailable():
    pytest.importorskip("chromadb")
    from neural_ledger.adapters.outbound.knowledge.chroma import ChromaKnowledgeBase

    def broken(texts):
        raise OSError("model not downloadable offline")

    with pytest.raises(KnowledgeBaseUnavailable):
        ChromaKnowledgeBase(CARDS[:1], None, "broken", embedding_function=broken).search("budget", "en", 1)


def _write(root: Path, lang: str, name: str, header: str, body: str = "Body.") -> None:
    (root / lang).mkdir(parents=True, exist_ok=True)
    (root / lang / f"{name}.md").write_text(f"---\n{header}\n---\n{body}\n", encoding="utf-8")


def test_the_loader_reads_header_and_body(tmp_path):
    _write(tmp_path, "en", "budget", '{"id": "budget", "lang": "en", "title": "Budget", "numbers": [{"key": "a", "value": 50, "unit": "%", "meaning": "m"}]}')
    (card,) = load_cards(tmp_path)
    assert (card.id, card.lang, card.title, card.body, card.numbers[0].value) == ("budget", "en", "Budget", "Body.", 50)


@pytest.mark.parametrize(
    ("lang", "name", "header", "message"),
    [
        ("en", "budget", '{"id": "budget", "lang": "en"', "invalid JSON"),
        ("en", "budget", '{"id": "budget", "lang": "en"}', "title"),
        ("fr", "budget", '{"id": "budget", "lang": "fr", "title": "Budget"}', "lang"),
        ("en", "other", '{"id": "budget", "lang": "en", "title": "Budget"}', "file name"),
        ("en", "budget", '{"id": "budget", "lang": "en", "title": "B", "sources": [{"title": "x"}]}', "source"),
    ],
)
def test_the_loader_names_the_file_of_a_bad_card(tmp_path, lang, name, header, message):
    _write(tmp_path, lang, name, header)
    with pytest.raises(ValueError, match=message) as error:
        load_cards(tmp_path)
    assert f"{name}.md" in str(error.value)


def test_chroma_reaches_a_server_when_given_a_url(monkeypatch):
    chromadb = pytest.importorskip("chromadb")
    from neural_ledger.adapters.outbound.knowledge.chroma import ChromaKnowledgeBase

    calls = []

    def http_client(host, port, ssl):
        calls.append((host, port, ssl))
        return chromadb.EphemeralClient()  # stands in for the server container

    monkeypatch.setattr(chromadb, "HttpClient", http_client)
    kb = ChromaKnowledgeBase(CARDS, None, "fake-bow-url", embedding_function=fake_embedding, url="http://chroma:8000")
    assert kb.search("budget", "en", 1)
    assert calls == [("chroma", 8000, False)]


def test_chroma_rejects_a_url_that_is_not_http():
    pytest.importorskip("chromadb")
    from neural_ledger.adapters.outbound.knowledge.chroma import ChromaKnowledgeBase

    with pytest.raises(KnowledgeBaseUnavailable):
        ChromaKnowledgeBase(CARDS, None, "fake-bow", embedding_function=fake_embedding, url="chroma:8000").search("budget", "en", 1)
