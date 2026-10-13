"""Table rebuild from boxes (pure) and the PDF text-layer path (needs the `pdf` extra)."""

from __future__ import annotations

import pytest

from neural_ledger.adapters.outbound.statements.ocr_tabular import (
    Box,
    Page,
    TableError,
    TableSpec,
    detect_format,
    read_pages,
    rebuild,
)

SPEC = TableSpec(
    header_required=frozenset({"fecha", "descripcion"}),
    header_tokens=frozenset({"fecha", "descripcion", "cheques", "depositos", "cargos", "abonos", "saldo", "y"}),
    stop_markers=("mensajes",),
)


def _word(x0: float, y: float, text: str, confidence: float = 1.0, width: float | None = None) -> Box:
    return Box(x0, x0 + (width if width is not None else 5.0 * len(text)), y, y + 8.0, text, confidence)


def _right(x1: float, y: float, text: str, confidence: float = 1.0) -> Box:
    """A right-aligned amount, as statements print them."""
    return Box(x1 - 5.0 * len(text), x1, y, y + 8.0, text, confidence)


def _page(straight: bool = True, source: str = "text") -> Page:
    boxes = [
        # Preamble: a summary line that also says "Saldo" and "Cargos" must not be taken as the header.
        _word(20, 10, "Saldo"), _word(60, 10, "Inicial"), _word(150, 10, "Cargos"), _word(250, 10, "Saldo"), _word(290, 10, "Final"),
        _word(20, 22, "1.000.000"), _word(150, 22, "8.580"), _word(250, 22, "991.420"),
        # Two-line header: CARGOS / ABONOS carry a second line that overlaps the first.
        _word(20, 40, "FECHA"), _word(80, 40, "DESCRIPCION"), _word(200, 40, "CHEQUES"),
        _word(270, 40, "DEPOSITOS"), _word(340, 40, "SALDO"),
        _word(200, 49, "Y", width=4), _word(206, 49, "CARGOS"), _word(270, 49, "Y", width=4), _word(276, 49, "ABONOS"),
        # Data: amounts end just before the next column's header, outside their own header word.
        _word(20, 62, "02/09"), _word(80, 62, "Compra"), _word(115, 62, "SHOP"), _right(266, 62, "3.280", 0.9),
        _word(80, 71, "Compra"), _word(115, 71, "CAFE"), _right(266, 71, "5.300", 0.4),
        _word(80, 80, "---"), _word(98, 80, "Saldo"), _word(125, 80, "Dia"), _word(145, 80, "---"), _right(380, 80, "991.420"),
        _word(20, 89, "04/09"), _word(80, 89, "PAGO"), _right(336, 89, "163.521"),
        # Footer after the stop marker is never data.
        _word(20, 120, "MENSAJES"), _word(20, 130, "INFORMESE"), _right(266, 130, "999"),
    ]  # fmt: skip
    return Page(1, tuple(boxes), source, straight)


def test_header_spans_two_lines_and_skips_lookalike_summary():
    table = rebuild(_page(), SPEC)
    assert table.header == ["FECHA", "DESCRIPCION", "CHEQUES Y CARGOS", "DEPOSITOS Y ABONOS", "SALDO"]
    assert table.preamble[0].startswith("Saldo Inicial")


def test_right_aligned_amounts_land_in_their_column():
    assert rebuild(_page(), SPEC).data == [
        ["02/09", "Compra SHOP", "3.280", "", ""],
        ["", "Compra CAFE", "5.300", "", ""],
        ["", "--- Saldo Dia ---", "", "", "991.420"],
        ["04/09", "PAGO", "", "163.521", ""],
    ]


def test_header_stops_at_the_first_line_with_a_non_header_word():
    narrow = TableSpec(SPEC.header_required, SPEC.header_tokens - {"cargos"}, SPEC.stop_markers)
    table = rebuild(_page(), narrow)
    assert table.header == ["FECHA", "DESCRIPCION", "CHEQUES", "DEPOSITOS", "SALDO"]
    assert table.data[0][2:4] == ["Y CARGOS", "Y ABONOS"]  # the second line became data, visibly


def test_text_layer_has_no_confidences_and_ocr_keeps_the_worst_box():
    assert rebuild(_page(), SPEC).confidences is None
    confs = rebuild(_page(source="ocr"), SPEC).data_confidences
    assert confs[0][2] == 0.9 and confs[1][2] == 0.4


def test_curved_page_path_gives_the_same_rows_on_a_flat_page():
    assert rebuild(_page(straight=False, source="ocr"), SPEC).data == rebuild(_page(), SPEC).data


def test_missing_header_is_an_error():
    page = Page(1, (_word(20, 10, "nothing"), _word(20, 30, "here")), "text", True)
    with pytest.raises(TableError):
        rebuild(page, SPEC)


def test_format_is_detected_from_content_not_name():
    assert detect_format(b"%PDF-1.7\n...") == "pdf"
    assert detect_format(b"\x89PNG\r\n\x1a\n....") == "image"
    assert detect_format(b"FECHA;DESCRIPCION") is None
    with pytest.raises(TableError):
        read_pages(b"plain text, not a statement")


def test_pdf_text_layer_reads_every_page():
    pymupdf = pytest.importorskip("pymupdf")
    pytest.importorskip("pdfplumber")
    doc = pymupdf.open()
    for n in (1, 2):
        page = doc.new_page()
        page.insert_text((40, 60), f"FECHA DESCRIPCION SALDO page {n}", fontsize=9)
    pages = read_pages(doc.tobytes())
    assert [p.number for p in pages] == [1, 2]
    assert all(p.source == "text" and p.straight for p in pages)
    assert "page 2" in pages[1].text
