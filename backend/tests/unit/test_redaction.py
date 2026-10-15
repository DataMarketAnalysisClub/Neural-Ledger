"""Redaction rules (ADR-028), both ways: each rule masks its target, and financial text stays readable.

Every name, RUT, account, address and number here is fictional.
"""

from __future__ import annotations

import pytest

from neural_ledger.domain.privacy.redaction import (
    PLACEHOLDER_CODES,
    Placeholder,
    Span,
    apply,
    check_digit,
    find_spans,
    mask_account,
    merge_spans,
    redact_text,
)


@pytest.mark.parametrize(
    ("text", "redacted"),
    [
        # the plan's examples
        ("0000000003 Transf a JUAN PEREZ 11.111.111-1", "[NUMBER] Transf a [PERSON] [ID]"),
        ("TEF DE MARIA SOTO maria.soto@mail.cl", "TEF DE [PERSON] [EMAIL]"),
        ("PAGO TARJETA 4555 1234 5678 9012", "PAGO TARJETA [NUMBER]"),
        ("0000000004 Transf a Ahorro", "[NUMBER] Transf a Ahorro"),
        # RUT / RUN: with or without dots and dash, a K check digit, a 7-digit body
        ("RUT 12.345.678-5", "RUT [ID]"),
        ("RUT 12345678-5", "RUT [ID]"),
        ("RUT 123456785", "RUT [ID]"),
        ("RUT 10.000.013-K", "RUT [ID]"),
        ("RUT 10.000.013-k", "RUT [ID]"),
        ("RUT 1.111.111-4", "RUT [ID]"),
        ("RUT 22.222.222 - 2", "RUT [ID]"),
        ("RUT 12.345.678-0", "RUT [NUMBER]"),  # a wrong check digit (typo, OCR) is masked all the same
        # long numbers: accounts, cards, transfer ids, split by dashes or spaces
        ("Cta 0-000-00-12345-6", "Cta [NUMBER]"),
        ("Cta 000-123-4567", "Cta [NUMBER]"),
        ("Pago 1234567", "Pago [NUMBER]"),
        ("Pago 4555  1234  5678  9012", "Pago [NUMBER]"),
        ("CUOTA 03/12 1234567", "CUOTA 03/12 [NUMBER]"),
        # email
        ("Aviso a juan.perez+banco@correo.example.cl", "Aviso a [EMAIL]"),
        # Chilean phones: mobile, Santiago and regional landlines, with or without +56
        ("Fono +56 9 8765 4321", "Fono [PHONE]"),
        ("Fono +56987654321", "Fono [PHONE]"),
        ("Fono (+56) 9 8765 4321", "Fono [PHONE]"),
        ("Fono 9 8765 4321", "Fono [PHONE]"),
        ("Fono 9-8765-4321", "Fono [PHONE]"),
        ("Fono 9.8765.4321", "Fono [PHONE]"),
        ("Fono (2) 2123 4567", "Fono [PHONE]"),
        ("Fono +56 2 2123 4567", "Fono [PHONE]"),
        ("Fono 41 212 3456", "Fono [PHONE]"),
        ("Fono (41) 212 3456", "Fono [PHONE]"),
        # names after a transfer keyword and A / DE / DESDE / PARA
        ("Transf a JUAN PEREZ", "Transf a [PERSON]"),
        ("Transf. de Juan Pérez", "Transf. de [PERSON]"),
        ("TRANSFERENCIA PARA ANA MARIA DE LA FUENTE", "TRANSFERENCIA PARA [PERSON]"),
        ("Traspaso desde PEDRO SOTO", "Traspaso desde [PERSON]"),
        ("TRANSF INTERNET A JUAN PEREZ", "TRANSF INTERNET A [PERSON]"),
        ("TRANSFERENCIA A TERCEROS JUAN PEREZ", "TRANSFERENCIA A TERCEROS [PERSON]"),
        ("Transferencia de fondos a JUAN PEREZ", "Transferencia de fondos a [PERSON]"),
        ("Transf a 11.111.111-1 JUAN PEREZ", "Transf a [ID] [PERSON]"),
        ("Transf a JUAN PEREZ (arriendo)", "Transf a [PERSON]"),
        ("Transf a JUAN PEREZ, gracias", "Transf a [PERSON]"),
        ("Transf a JUAN PEREZ CUOTA 03/12", "Transf a [PERSON] CUOTA 03/12"),
        ("Transf a Tarjeta de JUAN PEREZ", "Transf a Tarjeta de [PERSON]"),
    ],
)
def test_each_rule_masks_its_target(text, redacted):
    assert redact_text(text) == redacted


@pytest.mark.parametrize(
    "text",
    [
        # merchants, employers and payees are financial context
        "Compra Nacional MD JUMBO CONCEPCION",
        "Compra Nacional MD SHOP ONE",
        "PAGO PROVEEDOR COMERCIAL DEL SUR SPA",
        "REMUNERACION EMPRESA DEL NORTE LIMITADA",
        "Pagos Recurrentes MD NETFLIX",
        "SANTA ISABEL",
        # the estimator reads these
        "CUOTA 03/12",
        "COMPRA LIDER CUOTA 3/12",
        # short store numbers, amounts and dates
        "JUMBO 401",
        "COMPRA MAYORISTA 10",
        "SHOP 123456",
        "Compra $12.990",
        "Abono 1.116.492",
        "Cargo del 02/12/2025",
        # own accounts and generic transfers keep their words
        "Transf a Ahorro",
        "Transf a Cuenta Corriente",
        "Traspaso a Línea de Crédito",
        "TRASPASO DE FONDOS MUTUOS",
        "Transf a Tarjeta de Credito",
        "Transf a mi cuenta vista",
        "TRANSFERENCIA A TERCEROS",
        "COMISION TRANSFERENCIA A OTROS BANCOS",
        "TEF",
        "Pago TEF",
        # an @ that is not an address
        "PAGO @ TIENDA",
    ],
)
def test_financial_text_is_left_alone(text):
    assert redact_text(text) == text


def test_rut_check_digit_is_modulo_11():
    assert [check_digit(b) for b in ("11111111", "12345678", "1111111", "10000013", "10000004")] == ["1", "5", "4", "K", "0"]


def test_redacting_twice_is_redacting_once():
    texts = [
        "0000000003 Transf a JUAN PEREZ 11.111.111-1",
        "TEF DE MARIA SOTO maria.soto@mail.cl",
        "Transf a 1234567 JUAN 7654321 PEDRO",
        "Transf a JUAN PEREZ 11.111.111-1 BANCO ESTADO",
        "PEREZ11.111.111-1 Transf a PEREZ11.111.111-1",
        "Fono +56 9 8765 4321 y 4555 1234 5678 9012",
    ]
    for text in texts:
        once = redact_text(text)
        assert redact_text(once) == once, text


def test_placeholders_are_stable_codes_without_digits():
    assert PLACEHOLDER_CODES == ("PERSON", "ID", "NUMBER", "EMAIL", "PHONE", "ADDRESS")
    for placeholder in Placeholder:
        assert placeholder.tag == f"[{placeholder.value}]"
        assert not any(ch.isdigit() for ch in placeholder.tag) and "@" not in placeholder.tag
        assert find_spans(placeholder.tag) == ()


@pytest.mark.parametrize(
    ("account", "masked"),
    [("0-000-00-12345-6", "****3456"), ("000012345678", "****5678"), ("****3456", "****3456"), ("**** **** **** Ab3x", "****Ab3x"), ("1234", "****"), ("", "****")],
)
def test_account_reference_keeps_only_its_last_four_digits(account, masked):
    assert mask_account(account) == masked
    assert mask_account(masked) == masked


def test_apply_replaces_spans_and_merges_overlaps_into_the_most_specific_category():
    text = "Transf a JUAN 11.111.111-1"
    assert apply(text, ()) == text
    assert apply(text, [Span(9, 13, Placeholder.PERSON)]) == "Transf a [PERSON] 11.111.111-1"
    # A detector span overlapping a rule span: one placeholder covers both, ID beats NUMBER.
    merged = merge_spans([Span(14, 26, Placeholder.NUMBER), Span(14, 26, Placeholder.ID), Span(9, 13, Placeholder.PERSON)])
    assert merged == (Span(9, 13, Placeholder.PERSON), Span(14, 26, Placeholder.ID))
    assert merge_spans([Span(0, 5, Placeholder.PERSON), Span(3, 9, Placeholder.EMAIL)]) == (Span(0, 9, Placeholder.EMAIL),)
    assert merge_spans([Span(0, 4, Placeholder.PERSON), Span(4, 6, Placeholder.PERSON)]) == (Span(0, 6, Placeholder.PERSON),)


def test_a_span_can_only_add_masking():
    text = "0000000003 Transf a Ahorro"
    rules = find_spans(text)
    assert apply(text, rules) == "[NUMBER] Transf a Ahorro"
    assert apply(text, (*rules, Span(20, 26, Placeholder.PERSON))) == "[NUMBER] Transf a [PERSON]"


def test_spans_outside_the_text_or_empty_are_rejected():
    with pytest.raises(ValueError, match="outside"):
        apply("short", [Span(2, 9, Placeholder.NUMBER)])
    for start, end in ((3, 3), (5, 2), (-1, 4)):
        with pytest.raises(ValueError, match="not a span"):
            Span(start, end, Placeholder.PERSON)
