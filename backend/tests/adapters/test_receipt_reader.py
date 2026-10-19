"""ADR-038: reading a boleta from its print (text layer or OCR lines) and from its SII stamp (PDF417 + TED)."""

from __future__ import annotations

import importlib.util
from datetime import date

import pytest

from neural_ledger.adapters.outbound.receipts.boleta import money, parse_receipt
from neural_ledger.adapters.outbound.receipts.reader import ReceiptFileReader
from neural_ledger.adapters.outbound.receipts.stamp import MAX_TED, decode_stamp, parse_ted
from neural_ledger.application.ports import DocumentText, StatementUnreadable
from neural_ledger.domain.receipts.model import DocumentKind, kind_by_rules
from tests.receipt_samples import Boleta, boleta_lines, boleta_pdf, ted

HAS_ZXING = importlib.util.find_spec("zxingcpp") is not None


def _lines(texts, confidence=1.0):
    return [(t, confidence) for t in texts]


# ---- the print --------------------------------------------------------------------------------

def test_a_boleta_is_read_from_its_lines():
    read = parse_receipt(_lines(boleta_lines(Boleta())), "text")
    assert (read.issuer, read.issued_on, read.total, read.folio, read.issuer_rut) == (
        "SUPERMERCADO LOS ANDES SPA", date(2026, 10, 16), 12_990, "4471", "76.543.210-3",
    )
    assert (read.net, read.tax, read.source, read.confidence) == (10_916, 2_074, "text", None)


@pytest.mark.parametrize(
    ("line", "amount"),
    [("TOTAL $ 12.990", 12_990), ("TOTAL: 12990", 12_990), ("Total a pagar $1.234.567", 1_234_567), ("TOTAL (IVA INCLUIDO) $ 4.500", 4_500)],
)
def test_the_total_line_in_its_common_shapes(line, amount):
    assert parse_receipt(_lines(["STORE", line]), "text").total == amount


def test_subtotals_item_counts_and_tax_lines_are_not_the_total():
    lines = ["STORE", "SUBTOTAL $ 99.999", "TOTAL ITEMS 7", "TOTAL NETO $ 10.000", "IVA $ 1.900", "TOTAL $ 11.900"]
    assert parse_receipt(_lines(lines), "text").total == 11_900


def test_without_a_total_line_the_total_is_unknown_never_summed_from_the_items():
    assert parse_receipt(_lines(["STORE", "PAN $ 1.000", "LECHE $ 900"]), "text").total is None


@pytest.mark.parametrize(
    ("line", "on"),
    [("FECHA: 29/10/2026", date(2026, 10, 29)), ("Fecha 29-10-26 10:15", date(2026, 10, 29)), ("2026-10-29 10:15", date(2026, 10, 29)), ("31/02/2026", None)],
)
def test_dates_in_their_common_shapes(line, on):
    assert parse_receipt(_lines(["STORE", line]), "text").issued_on == on


def test_ocr_lines_keep_the_total_lines_confidence():
    lines = [("STORE", 0.9), ("TOTAL $ 1.000", 0.42)]
    assert parse_receipt(lines, "ocr").confidence == 0.42


@pytest.mark.parametrize(
    ("text", "value"),
    [("$ 12.990", 12_990), ("IVA 19% $ 2.074", 2_074), ("19%", None), ("no amount", None), ("$30 . 000", 30_000), ("1 , 500", 1_500)],
)
def test_money(text, value):
    assert money(text) == value


# ---- the SII stamp ------------------------------------------------------------------------------

def test_a_receipts_ted_gives_the_stamp():
    stamp = parse_ted(ted(Boleta()))
    assert stamp is not None
    assert (stamp.issuer_rut, stamp.document_type, stamp.folio, stamp.issued_on, stamp.total) == ("76543210-3", 39, 4471, date(2026, 10, 16), 12_990)
    assert (stamp.issuer_name, stamp.first_item) == ("SUPERMERCADO LOS ANDES SPA", "LECHE ENTERA 1L")


@pytest.mark.parametrize(
    "payload",
    [
        ted(Boleta(), document_type=33),  # a factura is not a receipt
        ted(Boleta()).replace("<MNT>12990</MNT>", "<MNT>doce mil</MNT>"),
        ted(Boleta()).replace("<FE>2026-10-16</FE>", "<FE>2026-13-01</FE>"),
        ted(Boleta()).replace("<RE>76543210-3</RE>", "<RE>not a rut</RE>", 1),
        "<TED>" + "x" * MAX_TED + "</TED>",
        "hello",
    ],
)
def test_anything_else_is_no_stamp(payload):
    assert parse_ted(payload) is None


def test_stamp_text_is_unescaped_and_kept_as_data():
    stamp = parse_ted(ted(Boleta(store="DON &amp; DOÑA")))
    assert stamp is not None and stamp.issuer_name == "DON & DOÑA"


def test_no_code_means_no_stamp():
    assert decode_stamp(boleta_pdf(Boleta(stamp=False)), "pdf") is None
    assert decode_stamp(b"not an image", "image") is None


# ---- the reader -------------------------------------------------------------------------------

def test_the_reader_routes_and_reads_a_text_layer_boleta():
    reader = ReceiptFileReader()
    pdf = boleta_pdf()
    peeked = reader.peek(pdf)
    assert peeked.format == "pdf" and kind_by_rules(peeked.text) is DocumentKind.RECEIPT
    read = reader.read_receipt(pdf)
    assert (read.total, read.issued_on, read.source) == (12_990, date(2026, 10, 16), "text")


@pytest.mark.skipif(not HAS_ZXING, reason="zxing-cpp (the `receipts` extra) is not installed")
def test_the_reader_decodes_the_stamp_printed_on_the_pdf():
    read = ReceiptFileReader().read_receipt(boleta_pdf(Boleta(stamp_total=19_990)))
    assert read.stamp is not None and (read.stamp.folio, read.stamp.total) == (4471, 19_990)


def test_a_spreadsheet_is_never_read_as_a_receipt():
    from tests.statement_samples import xlsx

    assert ReceiptFileReader().peek(xlsx([["Cartola"]])) == DocumentText("xlsx", "")


def test_unknown_bytes_are_unreadable():
    with pytest.raises(StatementUnreadable):
        ReceiptFileReader().peek(b"plain text, not a document")


# A card voucher "válido como boleta" photographed and read by OCR, as EasyOCR returned it (noise included).
OCR_VOUCHER = [
    "VALIDO COMO BOLETA",
    "DarescVot otescaa +1234",
    "53029868012 92282292",
    "25/04/2022 229250 AD: 290000041J19",
    "Iaraela Vsaea 2820arc",
    "Total $30 . 000",
    "Aprobasión 295161",
]


def test_a_noisy_ocr_voucher_keeps_its_total_and_date_and_no_invented_store():
    read = parse_receipt([(line, 0.7) for line in OCR_VOUCHER], "ocr")
    assert (read.total, read.issued_on, read.confidence) == (30_000, date(2026 - 4, 4, 25), 0.7)
    assert read.issuer == ""  # an address or a reference misread as letters is not a store name


# A restaurant's pre-bill photographed on thermal paper, as OCR returns it: "$" read as "8", TOTAL as "Tota]", the
# separators doubled, the amount under its label, and a per-diner share that is not what was paid. Fictional venue.
OCR_RESTAURANT_BILL = [
    "LA PICADA DEL PUERTO",
    "PROVIDENCIA SANTIAGO",
    "FaCtura PRoFORHA",
    "10-10-2026 22:39",
    "Uds Producto",
    "Importe",
    "MO XL MANGO 85.990",
    "PAPAS TRADICIONAL $4,990",
    "C/ITALIANO NORMAL 83,990",
    "CHORRILLANA TEXAS $10,990",
    "MO XL MARACUYA 821 ,160",
    "Tota]   (Inpuestos Inc] ,) 8107,.320",
    "Propina Suger ida 10,00",
    "810.732",
    "Tota] (Propina Inc] )",
    "8118.052",
    "eS; Tota 1/ Comensa 1",
    "= 826 ,830",
]


def test_a_photographed_restaurant_bill_is_a_receipt_with_the_total_paid():
    from neural_ledger.domain.receipts.model import kind_by_rules

    assert kind_by_rules("\n".join(OCR_RESTAURANT_BILL)) is DocumentKind.RECEIPT
    read = parse_receipt([(line, 0.6) for line in OCR_RESTAURANT_BILL], "ocr")
    assert (read.total, read.issued_on, read.issuer) == (118_052, date(2026, 10, 10), "LA PICADA DEL PUERTO")


def test_a_leading_eight_is_a_dollar_sign_only_when_most_amounts_start_with_it():
    mostly_eights = ["STORE", "A 811.980", "B 87.990", "C $4.990", "TOTAL 824.970"]
    assert parse_receipt([(line, 0.6) for line in mostly_eights], "ocr").total == 24_970
    real_eights = ["STORE", "A 8.990", "B 1.990", "C 2.500", "D 3.100", "TOTAL 16.580"]
    assert parse_receipt([(line, 0.6) for line in real_eights], "ocr").total == 16_580
    # A text layer is never corrected: what the PDF says is what it says.
    assert parse_receipt([(line, 1.0) for line in mostly_eights], "text").total == 824_970


def test_a_total_whose_amount_is_on_the_next_line():
    assert parse_receipt([("STORE", 1.0), ("TOTAL A PAGAR", 1.0), ("$ 5.500", 1.0)], "text").total == 5_500
    assert parse_receipt([("STORE", 1.0), ("TOTAL", 1.0), ("GRACIAS POR SU COMPRA", 1.0)], "text").total is None
