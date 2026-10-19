"""Synthetic boletas for tests and the demo. The repository is public: never commit a real receipt.

`boleta_pdf` draws a fictional supermarket's boleta electrónica with a text layer and, when zxing-cpp is
installed, its SII stamp as a real PDF417 code holding a TED, so the whole read path (pdfplumber → parse_receipt,
pymupdf → zxing-cpp → parse_ted) is exercised. RUTs are fictional and pass the check digit.
"""

from __future__ import annotations

from dataclasses import dataclass

ISSUER_RUT = "76.543.210-3"
TED_RUT = "76543210-3"


@dataclass(frozen=True)
class Boleta:
    store: str = "SUPERMERCADO LOS ANDES SPA"
    folio: int = 4471
    issued_on: str = "2026-10-16"  # ISO; printed as DD/MM/YYYY
    items: tuple[tuple[str, int], ...] = (("LECHE ENTERA 1L", 1_090), ("PAN AMASADO 1KG", 2_400), ("QUESO GAUDA 250G", 3_990), ("CAFE GRANO 500G", 5_510))
    printed_total: int | None = None  # None: the sum of the items
    stamp_total: int | None = None  # None: the printed total; another value makes the stamp disagree
    stamp: bool = True
    tax_line: bool = True
    extra_line: str | None = None  # e.g. an injection attempt printed on the receipt

    @property
    def total(self) -> int:
        return self.printed_total if self.printed_total is not None else sum(price for _, price in self.items)


def _fmt(amount: int) -> str:
    return f"{amount:,}".replace(",", ".")


def ted(b: Boleta, document_type: int = 39) -> str:
    total = b.stamp_total if b.stamp_total is not None else b.total
    return (
        f'<TED version="1.0"><DD><RE>{TED_RUT}</RE><TD>{document_type}</TD><F>{b.folio}</F><FE>{b.issued_on}</FE>'
        f"<RR>66666666-6</RR><RSR>CLIENTE</RSR><MNT>{total}</MNT><IT1>{b.items[0][0]}</IT1>"
        f'<CAF version="1.0"><DA><RE>{TED_RUT}</RE><RS>{b.store}</RS><TD>{document_type}</TD><RNG><D>1</D><H>9999</H></RNG>'
        f"<FA>2026-01-02</FA><IDK>100</IDK></DA><FRMA algoritmo=\"SHA1withRSA\">AAAA</FRMA></CAF>"
        f"<TSTED>{b.issued_on}T10:15:00</TSTED></DD><FRMT algoritmo=\"SHA1withRSA\">BBBB</FRMT></TED>"
    )


def stamp_png(payload: str) -> bytes | None:
    try:
        import io

        import zxingcpp
        from PIL import Image
    except ImportError:
        return None
    image = zxingcpp.create_barcode(payload, zxingcpp.BarcodeFormat.PDF417).to_image(scale=3)
    buffer = io.BytesIO()
    Image.fromarray(__import__("numpy").asarray(image)).save(buffer, format="PNG")
    return buffer.getvalue()


def boleta_lines(b: Boleta) -> list[str]:
    day = f"{b.issued_on[8:10]}/{b.issued_on[5:7]}/{b.issued_on[:4]}"
    lines = [b.store, f"R.U.T.: {ISSUER_RUT}", f"BOLETA ELECTRONICA N° {b.folio}", "AV. SIEMPRE VIVA 742, SANTIAGO", f"FECHA: {day} 10:15"]
    lines += [f"{name}  $ {_fmt(price)}" for name, price in b.items]
    if b.extra_line:
        lines.append(b.extra_line)
    lines.append(f"TOTAL  $ {_fmt(b.total)}")
    if b.tax_line:
        net = round(b.total / 1.19)
        lines += [f"MONTO NETO  $ {_fmt(net)}", f"IVA 19%  $ {_fmt(b.total - net)}"]
    lines += ["EFECTIVO  $ 20.000", f"VUELTO  $ {_fmt(20_000 - b.total)}", "Timbre Electronico SII", "Res. Ex. 80 de 2014 Verifique documento: www.sii.cl"]
    return lines


def boleta_pdf(b: Boleta | None = None) -> bytes:
    import pymupdf

    b = b or Boleta()
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=620)
    y = 30.0
    for line in boleta_lines(b):
        page.insert_text((20, y), line, fontsize=9, fontname="cour")
        y += 16
    png = stamp_png(ted(b)) if b.stamp else None
    if png is not None:
        page.insert_image(pymupdf.Rect(20, y + 10, 280, y + 110), stream=png)
    data = doc.tobytes()
    doc.close()
    return data
