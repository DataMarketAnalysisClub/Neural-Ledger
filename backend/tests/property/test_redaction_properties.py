"""Redaction properties (hypothesis): generated personal data never survives, and redacting is idempotent.

The RUT check digit is computed here independently of the domain, so the rules are not tested against themselves.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from neural_ledger.domain.privacy.redaction import PLACEHOLDER_CODES, redact_text

pytestmark = pytest.mark.property

SETTINGS = settings(max_examples=300, deadline=None, derandomize=True)  # cheap rules: more examples, same ones every run
DIGITS = "0123456789"

# Words that carry no personal data and no digits: merchants, bank wording, transfer keywords.
WORDS = (
    "Compra", "Nacional", "MD", "JUMBO", "SANTA", "ISABEL", "LIDER", "PAGO", "PROVEEDOR", "REMUNERACION", "Fondo",
    "Mutuo", "NETFLIX", "COPEC", "SHOP", "Pagos", "Recurrentes", "EXPRESS", "CONCEPCION", "Transf", "a", "TEF", "DE",
)  # fmt: skip
filler = st.lists(st.sampled_from(WORDS), max_size=3).map(" ".join)


def _dv(body: int) -> str:
    total = sum(int(d) * (2 + i % 6) for i, d in enumerate(reversed(str(body))))
    rest = 11 - total % 11
    return {11: "0", 10: "K"}.get(rest, str(rest))


@st.composite
def ruts(draw) -> str:
    body = draw(st.integers(1_000_000, 99_999_999))
    dv = _dv(body)
    if dv == "K":
        dv = draw(st.sampled_from(("K", "k")))
    dotted = f"{body:,}".replace(",", ".")
    return draw(st.sampled_from((f"{dotted}-{dv}", f"{body}-{dv}", f"{body}{dv}")))


emails = st.from_regex(r"[a-z][a-z0-9._]{0,12}[a-z0-9]@[a-z]{2,10}\.(cl|com|net|org)", fullmatch=True)


@st.composite
def phones(draw) -> str:
    rest = draw(st.text(DIGITS, min_size=7, max_size=7))
    kind = draw(st.sampled_from(("mobile", "santiago", "region")))
    if kind == "mobile":
        n = draw(st.sampled_from(DIGITS)) + rest  # 9 + 8 digits
        a, b = n[:4], n[4:]
        formats = (f"+56 9 {a} {b}", f"+569{n}", f"56 9 {a} {b}", f"(+56) 9 {a} {b}", f"9 {a} {b}", f"9{n}", f"9-{a}-{b}", f"9.{a}.{b}")
    elif kind == "santiago":
        a, b = "2" + rest[:3], rest[3:]  # 2 + 2xxx xxxx
        formats = (f"+56 2 {a} {b}", f"(2) {a} {b}", f"2 {a} {b}", f"+562{a}{b}")
    else:
        area = draw(st.sampled_from(("32", "35", "41", "45", "51", "58", "61", "67", "71", "75")))
        a, b = rest[:3], rest[3:]
        formats = (f"+56 {area} {a} {b}", f"({area}) {a} {b}", f"{area} {a} {b}", f"+56{area}{rest}")
    return draw(st.sampled_from(formats))


@st.composite
def long_numbers(draw) -> str:
    """7 to 19 digits, as written for accounts and cards: whole, or split by spaces or dashes."""
    digits = draw(st.text(DIGITS, min_size=7, max_size=19))
    cuts = sorted(draw(st.sets(st.integers(1, len(digits) - 1), max_size=4)))
    parts, previous = [], 0
    for cut in cuts:
        parts += [digits[previous:cut], draw(st.sampled_from((" ", "-", " - ")))]
        previous = cut
    return "".join([*parts, digits[previous:]])


personal = st.one_of(ruts(), emails, phones(), long_numbers())


@SETTINGS
@given(st.lists(st.tuples(filler, personal), min_size=1, max_size=4), filler)
def test_generated_personal_data_never_survives(pairs, tail):
    text = " ".join(part for words, value in pairs for part in (words, value) if part) + (f" {tail}" if tail else "")
    redacted = redact_text(text)
    assert not any(ch.isdigit() for ch in redacted), (text, redacted)  # the filler has none, and placeholders have none
    assert "@" not in redacted
    assert all(value not in redacted for _, value in pairs)
    assert redact_text(redacted) == redacted


@SETTINGS
@given(st.text())
def test_redacting_twice_is_redacting_once(text):
    once = redact_text(text)
    assert redact_text(once) == once


@SETTINGS
@given(st.text(alphabet=st.characters(blacklist_characters="[]")))
def test_only_known_placeholders_are_inserted(text):
    inserted = redact_text(text).split("[")[1:]
    assert all(part.split("]", 1)[0] in PLACEHOLDER_CODES for part in inserted)


MERCHANTS = ("Compra Nacional MD", "JUMBO", "SANTA ISABEL", "LIDER EXPRESS", "PAGO PROVEEDOR", "REMUNERACION", "NETFLIX", "SHOP")
financial_phrase = st.one_of(
    st.sampled_from(MERCHANTS),
    st.tuples(st.sampled_from(MERCHANTS), st.integers(1, 9_999)).map(lambda t: f"{t[0]} {t[1]}"),  # short store numbers
    st.tuples(st.integers(1, 48), st.integers(1, 48)).map(lambda t: f"CUOTA {t[0]:02d}/{t[1]:02d}"),
)


@SETTINGS
@given(st.lists(financial_phrase, min_size=1, max_size=5).map(" ".join))
def test_merchants_cuotas_and_store_numbers_survive(text):
    assert redact_text(text) == text
