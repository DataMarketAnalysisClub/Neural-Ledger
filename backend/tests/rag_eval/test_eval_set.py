"""The question set stays well formed and the lexical baseline is pinned (offline, no model; ADR-040)."""

from __future__ import annotations

from collections import Counter

import pytest

from neural_ledger.adapters.outbound.knowledge.corpus_loader import load_cards
from neural_ledger.adapters.outbound.knowledge.lexical import LexicalKnowledgeBase
from neural_ledger.domain.education.concepts import LANGUAGES, ConceptCard, Passage
from tests.rag_eval.run import K, answerable, load_questions, score

QUESTIONS = load_questions()
CARD_IDS = frozenset(c.id for c in load_cards())


def test_every_question_is_well_formed_and_unique():
    assert len({q["q"] for q in QUESTIONS}) == len(QUESTIONS) >= 40
    for q in QUESTIONS:
        assert set(q) == {"q", "lang", "expected"}
        assert q["lang"] in LANGUAGES and q["q"].strip() and isinstance(q["expected"], list)
        assert all(i in CARD_IDS for i in q["expected"]), q


def test_the_set_covers_every_concept_both_languages_and_off_topic_questions():
    assert {i for q in QUESTIONS for i in q["expected"]} == CARD_IDS
    assert min(Counter(q["lang"] for q in QUESTIONS).values()) >= 15
    assert sum(1 for q in QUESTIONS if not q["expected"]) >= 4


def test_score_counts_recall_and_mrr():
    card = {i: ConceptCard(i, "en", i, "body") for i in ("a", "b")}
    questions = [{"q": "x", "lang": "en", "expected": ["a"]}, {"q": "y", "lang": "en", "expected": ["a"]}, {"q": "z", "lang": "en", "expected": []}]
    results = [[Passage(card["a"], "", 0.9)], [Passage(card["b"], "", 0.8), Passage(card["a"], "", 0.5)], [Passage(card["b"], "", 0.1)]]
    report = score(questions, results)
    assert report["all"] == {"n": 2, "recall@1": 0.5, "recall@3": 1.0, "mrr": 0.75}
    assert report["top_score"]["off_topic_max"] == 0.1


def test_lexical_baseline():
    """recall@3 >= 0.8 on the questions whose cards exist (the plan's bar for the offline index)."""
    cards = load_cards()
    questions, _ = answerable(QUESTIONS, {c.id for c in cards})
    on_topic = [q for q in questions if q["expected"]]
    if len(on_topic) < 2:
        pytest.skip("fewer than two answerable questions: the cards are not written yet")
    kb = LexicalKnowledgeBase(cards)
    report = score(questions, [kb.search(q["q"], q["lang"], K) for q in questions])
    assert report["all"]["recall@3"] >= 0.8, report["misses"]
