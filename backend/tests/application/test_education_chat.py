"""EXPLAIN turns answer from the concept cards (ADR-040), in Spanish and English, with the not-advice caveat."""

from __future__ import annotations

import pytest

from neural_ledger.adapters.outbound.text.lexicon import INTENT_PATTERNS, language_of
from neural_ledger.application.services.knowledge_threshold import ThresholdKnowledgeBase
from neural_ledger.domain.education.concepts import NOT_ADVICE
from neural_ledger.domain.shared.envelope import Status
from tests.education_fakes import CARDS, ETF_ES, FakeKnowledgeBase, education, education_chat

USER = "camila"


def _first_intent(text: str) -> str:
    return next((i.value for i, p in INTENT_PATTERNS if p.search(text)), "smalltalk")


@pytest.mark.parametrize(
    "text, intent",
    [
        ("¿Qué es un ETF?", "explain"),
        ("¿Qué es un fondo mutuo?", "explain"),
        ("¿Qué es el APV?", "explain"),
        ("¿Qué es un bono?", "explain"),
        ("¿Qué es una acción?", "explain"),
        ("¿Qué son las criptomonedas?", "explain"),
        ("What is an ETF?", "explain"),
        ("What is a stock?", "explain"),
        ("¿En qué invierto?", "out_of_scope"),
        ("¿Qué acción compro?", "out_of_scope"),
        ("Should I buy bitcoin?", "out_of_scope"),
        ("Recomiéndame un fondo mutuo", "out_of_scope"),
        ("¿Qué es mejor, acciones o bonos?", "out_of_scope"),
        ("What is the best ETF?", "out_of_scope"),
    ],
)
def test_definitions_are_explained_and_advice_is_out_of_scope(text, intent):
    assert _first_intent(text) == intent


@pytest.mark.parametrize("text, lang", [("¿Qué es un ETF?", "es"), ("What is an ETF?", "en"), ("explícame el APV", "es")])
def test_language_of_the_question(text, lang):
    assert language_of(text) == lang


@pytest.mark.parametrize(
    "text, lang, title, definition, caveat",
    [
        ("¿Qué es un ETF?", "es", "ETF (fondo cotizado)", "Un ETF es un fondo que se compra y se vende en la bolsa", "información general"),
        ("What is an ETF?", "en", "ETF (exchange-traded fund)", "An ETF is a fund that is bought and sold on the stock exchange", "general information"),
    ],
)
def test_explain_answers_from_the_card_in_the_users_language(services, adapters, text, lang, title, definition, caveat):
    kb = FakeKnowledgeBase()
    reply = education_chat(services, adapters, kb).handle(f"s-edu-{lang}", USER, text)
    assert reply.intent == "explain" and reply.tools_called == ("search_financial_concepts",)
    assert kb.searches == [(text, lang, 3)]
    assert title in reply.text and definition in reply.text and caveat in reply.text
    assert "100" in reply.text  # the card's figure, said because it is a fact
    assert reply.verification.ok and not reply.fallback_used
    assert NOT_ADVICE in reply.warnings
    assert {f.key for f in reply.facts} == {"etf.minimum_investment", "etf.annual_fee"}
    calls = [e.draft for e in adapters.audit_log.events() if e.draft.kind.value == "TOOL_CALL"]
    assert calls[-1].tool_requested == "search_financial_concepts" and calls[-1].permission_tier == "T0"
    assert calls[-1].execution_result == "OK"


@pytest.mark.parametrize(
    "text, expected", [("¿Qué es el interés compuesto?", "No tengo una ficha"), ("What is compound interest?", "I don't have a card")]
)
def test_no_card_means_no_explanation_from_memory(services, adapters, text, expected):
    reply = education_chat(services, adapters, FakeKnowledgeBase(cards=())).handle("s-edu-none", USER, text)
    assert reply.tools_called == ("search_financial_concepts",)
    assert expected in reply.text and reply.verification.ok and reply.facts == ()


def test_a_card_below_the_floor_is_not_an_explanation(services, adapters):
    reply = education_chat(services, adapters, FakeKnowledgeBase(score=0.1), min_score=0.3).handle("s-edu-low", USER, "What is an ETF?")
    assert "I don't have a card" in reply.text and "ETF (exchange" not in reply.text


def test_an_unavailable_index_is_said_never_raised(services, adapters):
    reply = education_chat(services, adapters, FakeKnowledgeBase(unavailable=True)).handle("s-edu-down", USER, "¿Qué es un ETF?")
    assert "no están disponibles" in reply.text and reply.verification.ok


def test_the_per_index_floor_drops_weak_passages():
    kb = ThresholdKnowledgeBase(FakeKnowledgeBase(score=0.4), 0.45)
    assert kb.name == "fake/0001" and kb.search("etf", "es", 3) == ()
    assert len(ThresholdKnowledgeBase(FakeKnowledgeBase(score=0.5), 0.45).search("etf", "es", 3)) == 1


@pytest.mark.parametrize(
    "query, lang, k, field",
    [("", None, 3, "query"), ("   ", None, 3, "query"), ("x" * 301, None, 3, "query"), (42, None, 3, "query"),
     ("etf", "fr", 3, "lang"), ("etf", None, 0, "k"), ("etf", None, 6, "k"), ("etf", None, True, "k"), ("etf", None, 2.5, "k")],
)
def test_explain_validates_its_input(query, lang, k, field):
    kb = FakeKnowledgeBase()
    result = education(kb).explain(USER, query, lang, k)
    assert result.status is Status.INVALID_INPUT and result.field == field and kb.searches == []


def test_language_defaults_to_the_profile_then_spanish(services):
    kb = FakeKnowledgeBase()
    education(kb).explain(USER, "etf")
    assert kb.searches[-1][1] == "es"

    class Profiles:
        def get(self, user_id):
            from types import SimpleNamespace

            return SimpleNamespace(language="en")

    education(kb, profiles=Profiles()).explain(USER, "etf")
    assert kb.searches[-1][1] == "en"


def test_the_envelope_carries_passages_as_untrusted_data_and_numbers_as_facts():
    result = education(FakeKnowledgeBase(cards=CARDS)).explain(USER, "etf", "es", 3)
    assert result.ok and result.snapshot_id.startswith("edu_")
    concept = result.data["concepts"][0]
    assert concept["passage"] == {"untrusted_text": ETF_ES.body} and result.data["knowledge_base"] == "fake/0001"
    assert result.warnings == (NOT_ADVICE,)
