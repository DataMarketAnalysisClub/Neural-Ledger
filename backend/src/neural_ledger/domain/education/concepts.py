"""Concept cards and the envelope an explanation is built from (ADR-039).

A concept card is a short, team-written explanation of one financial term in one language. Cards are
education, never advice: they define a term, they never recommend a product, a security or an amount.

Every number a card's text uses is declared in its `numbers`, so the passage reaches the agent as facts
and the response verifier accepts it (CLAUDE.md rule 4). Card text is retrieved content: it travels to
the model wrapped as untrusted data, like merchant text (rule 8).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..agent.untrusted import wrap_passage
from ..shared.envelope import Caveat, Envelope, Fact, Status

EDUCATION_VERSION = "edu-0.1"  # card format + retrieval threshold + envelope shape; outputs carry it as params_version
LANGUAGES = ("es", "en")

# The explanation must say it is general education. Any one of these tokens counts as mentioning it.
NOT_ADVICE = Caveat(
    code="EDUCATIONAL_NOT_ADVICE",
    message="General financial education, not a recommendation for your situation.",
    must_mention=(
        "not advice",
        "not a recommendation",
        "general information",
        "educational",
        "no es una recomendación",
        "no es asesoría",
        "información general",
        "educativ",
    ),
)


@dataclass(frozen=True, slots=True)
class CardNumber:
    """A number the card's text uses, with its unit and what it means."""

    key: str
    value: int | float
    unit: str
    meaning: str


@dataclass(frozen=True, slots=True)
class Source:
    title: str
    url: str
    license: str  # e.g. "reference only (own words)", "CC BY 4.0"


@dataclass(frozen=True, slots=True)
class ConceptCard:
    id: str  # snake_case, the same across languages
    lang: str  # one of LANGUAGES
    title: str
    body: str
    aliases: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    related: tuple[str, ...] = ()
    sources: tuple[Source, ...] = ()
    numbers: tuple[CardNumber, ...] = ()


@dataclass(frozen=True, slots=True)
class Passage:
    """One retrieved card (or part of one) with its relevance score in [0, 1]."""

    card: ConceptCard
    text: str
    score: float


def explanation_envelope(passages: Sequence[Passage], kb_name: str, min_score: float) -> Envelope[dict]:
    """The envelope an explanation is built from: passages as untrusted data, card numbers as facts.

    Passages below `min_score` are dropped; with none left the answer is INSUFFICIENT_DATA, so the agent
    says it has no card for that instead of explaining from memory.
    """
    kept = [p for p in passages if p.score >= min_score]
    if not kept:
        return Envelope(Status.INSUFFICIENT_DATA, EDUCATION_VERSION, missing=("concept",), message="no concept card matches the question")
    facts: list[Fact] = []
    seen: set[str] = set()
    for p in kept:
        for n in p.card.numbers:
            key = f"{p.card.id}.{n.key}"
            if key not in seen:
                seen.add(key)
                facts.append(Fact(key, n.value, n.unit, f"concept card {p.card.id} ({p.card.lang}): {n.meaning}"))
    data = {
        "knowledge_base": kb_name,
        "concepts": [
            {
                "id": p.card.id,
                "lang": p.card.lang,
                "title": p.card.title,
                "passage": wrap_passage(p.text),
                "score": round(p.score, 3),
                "related": list(p.card.related),
                "sources": [{"title": s.title, "url": s.url} for s in p.card.sources],
            }
            for p in kept
        ],
    }
    return Envelope(Status.OK, EDUCATION_VERSION, data=data, facts=tuple(facts), warnings=(NOT_ADVICE,))
