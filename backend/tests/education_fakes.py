"""Synthetic concept cards and an in-test knowledge base for the education tests (ADR-040).

The cards are written for the tests, not taken from the corpus, so the tests do not change when the corpus does.
`education_chat` builds a chat turn exactly like production, with this knowledge base in place of the real one.
"""

from __future__ import annotations

from collections.abc import Sequence

from neural_ledger.adapters.outbound.decision.rules import RulesDecisionModel
from neural_ledger.adapters.outbound.llm.scripted import ScriptedLanguageModel
from neural_ledger.adapters.outbound.persistence.memory import InMemoryConversationStore
from neural_ledger.adapters.outbound.system.ids import UuidIds
from neural_ledger.application.catalog import build_registry
from neural_ledger.application.ports import KnowledgeBaseUnavailable
from neural_ledger.application.services.decisions import DecisionService
from neural_ledger.application.services.tools import ToolRegistry
from neural_ledger.application.use_cases.chat import ChatUseCase
from neural_ledger.application.use_cases.education import EducationUseCases
from neural_ledger.bootstrap.contracts import load_tool_definitions
from neural_ledger.domain.agent.policy import AP_0_1
from neural_ledger.domain.education.concepts import CardNumber, ConceptCard, Passage, Source
from neural_ledger.domain.permissions.policy import PP_0_1
from tests.conftest import CONTRACTS

_SOURCES = (Source("Test source", "https://example.org/etf", "reference only (own words)"),)
_NUMBERS = (
    CardNumber("minimum_investment", 100_000, "CLP", "an example minimum investment some brokers ask for"),
    CardNumber("annual_fee", 0.5, "%", "an example annual fee"),
)

ETF_ES = ConceptCard(
    id="etf",
    lang="es",
    title="ETF (fondo cotizado)",
    body=(
        "# ETF\n\nUn ETF es un fondo que se compra y se vende en la bolsa como si fuera una acción. "
        "Algunas corredoras piden un mínimo de 100.000 CLP para invertir en uno. "
        "Muchos cobran una comisión anual cercana a 0,5%."
    ),
    aliases=("fondo cotizado", "exchange traded fund"),
    tags=("investing",),
    related=("mutual_fund", "diversification"),
    sources=_SOURCES,
    numbers=_NUMBERS,
)
ETF_EN = ConceptCard(
    id="etf",
    lang="en",
    title="ETF (exchange-traded fund)",
    body=(
        "# ETF\n\nAn ETF is a fund that is bought and sold on the stock exchange as if it were a share. "
        "Some brokers ask for a minimum of 100,000 CLP to invest in one. "
        "Many charge an annual fee close to 0.5%."
    ),
    aliases=("exchange traded fund",),
    tags=("investing",),
    related=("mutual_fund", "diversification"),
    sources=_SOURCES,
    numbers=_NUMBERS,
)
CARDS = (ETF_ES, ETF_EN)


class FakeKnowledgeBase:
    """Returns the cards in the asked language with a fixed score; records every search."""

    name = "fake/0001"

    def __init__(self, cards: Sequence[ConceptCard] = CARDS, score: float = 0.9, unavailable: bool = False) -> None:
        self._cards = tuple(cards)
        self._score = score
        self._unavailable = unavailable
        self.searches: list[tuple[str, str, int]] = []

    def search(self, query: str, lang: str, k: int) -> Sequence[Passage]:
        self.searches.append((query, lang, k))
        if self._unavailable:
            raise KnowledgeBaseUnavailable("the index is down")
        return tuple(Passage(c, c.body, self._score) for c in self._cards if c.lang == lang)[:k]


def education(kb, min_score: float = 0.3, profiles=None) -> EducationUseCases:
    return EducationUseCases(kb, min_score, profiles)


def registry_with(services, adapters, kb, min_score: float = 0.3) -> ToolRegistry:
    return build_registry(
        services.financial, services.actions, services.profiles, services.audit, services.documents,
        education(kb, min_score), load_tool_definitions(CONTRACTS), adapters.audit_log, adapters.clock, UuidIds(), PP_0_1.version,
    )


def education_chat(services, adapters, kb, llm=None, min_score: float = 0.3) -> ChatUseCase:
    return ChatUseCase(
        DecisionService([RulesDecisionModel()], AP_0_1), llm or ScriptedLanguageModel(), registry_with(services, adapters, kb, min_score),
        services.financial, adapters.audit_log, InMemoryConversationStore(), adapters.clock, UuidIds(), AP_0_1,
    )
