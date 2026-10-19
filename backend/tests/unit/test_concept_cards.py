"""The real concept-card corpus keeps the rules of corpus/README.md (ADR-039).

Every card loads; every id exists in Spanish and English; every number the body says is declared (the verifier
only lets the agent say facts); no guarantee or "safe" wording; 120-280 words; sources with an https link and a
licence; no links in the body.
"""

from __future__ import annotations

import re
from collections import defaultdict
from decimal import Decimal

import pytest

from neural_ledger.adapters.outbound.knowledge.corpus_loader import load_cards
from neural_ledger.domain.agent.verification import extract_numbers
from neural_ledger.domain.education.concepts import LANGUAGES

CARDS = load_cards()
IDS = {c.id for c in CARDS}

# The verifier's banned wording plus the README's: "safe", guarantees, "risk-free". "seguro" alone is not banned,
# because it also means insurance; "dinero seguro" and "sin riesgo" are.
BANNED = re.compile(
    r"\bsafe(?:ly)?\b|\bguarantee\w*|\bgarantiz\w*|\brisk[- ]free\b|\bsin riesgo\b|\blibre de riesgo\b|\bdinero seguro\b|\bplata segura\b",
    re.IGNORECASE,
)


def _card_id(card) -> str:
    return f"{card.lang}/{card.id}"


def test_the_corpus_loads_and_is_not_empty():
    assert CARDS
    assert all(c.lang in LANGUAGES for c in CARDS)


def test_every_id_exists_in_every_language():
    langs = defaultdict(set)
    for c in CARDS:
        langs[c.id].add(c.lang)
    missing = {i: sorted(set(LANGUAGES) - found) for i, found in langs.items() if found != set(LANGUAGES)}
    assert not missing, f"cards missing a language: {missing}"


def test_ids_are_snake_case_and_related_ids_are_known():
    for c in CARDS:
        assert re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*", c.id), c.id
        unknown = [r for r in c.related if r not in IDS]
        assert not unknown, f"{_card_id(c)} relates to unknown ids {unknown}"
        assert c.id not in c.related


@pytest.mark.parametrize("card", CARDS, ids=_card_id)
def test_every_number_in_the_body_is_declared(card):
    for number in extract_numbers(card.body):
        declared = [n for n in card.numbers if (n.unit == "%") == number.is_percent and Decimal(str(n.value)) == number.value]
        assert declared, f"{_card_id(card)}: {number.text!r} is not in `numbers`"


@pytest.mark.parametrize("card", CARDS, ids=_card_id)
def test_no_banned_wording(card):
    for text in (card.title, card.body, *card.aliases):
        found = BANNED.search(text)
        assert not found, f"{_card_id(card)}: banned wording {found.group(0)!r}"


@pytest.mark.parametrize("card", CARDS, ids=_card_id)
def test_the_body_is_short_and_starts_with_a_definition(card):
    words = len(card.body.split())
    assert 120 <= words <= 280, f"{_card_id(card)}: {words} words"
    first = card.body.split("\n\n")[0].strip()
    assert first and not first.startswith(("-", "*", "#")), f"{_card_id(card)}: the first paragraph must be the definition"
    assert "http" not in card.body and "www." not in card.body, f"{_card_id(card)}: links belong in `sources`"


@pytest.mark.parametrize("card", CARDS, ids=_card_id)
def test_every_source_has_a_title_an_https_link_and_a_licence(card):
    assert card.sources, f"{_card_id(card)} lists no source"
    for s in card.sources:
        assert s.title.strip() and s.license.strip(), f"{_card_id(card)}: {s}"
        assert s.url.startswith("https://"), f"{_card_id(card)}: {s.url}"
