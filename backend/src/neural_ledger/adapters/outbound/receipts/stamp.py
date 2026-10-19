"""The SII stamp (timbre electrónico) of a boleta electrónica: its PDF417 code and the TED it carries.

Every electronic receipt in Chile prints a PDF417 code holding the TED, a small XML signed by the issuer with
the SII's folio authorization (CAF): the issuer's RUT, the document type, the folio, the date and the total.
The code is decoded with zxing-cpp (Apache-2.0, the `receipts` extra) and the TED is read with regular expressions,
never with an XML parser: it is third-party input, and only six fixed fields are needed. The signature is not
checked here; the stamp confirms the print, it does not prove it.

Optional by design: without zxing-cpp, or without pymupdf to rasterize a PDF, a receipt is read from its print alone.
"""

from __future__ import annotations

import html
import io
import logging
import re
from datetime import date

from ....domain.receipts.model import ReceiptStamp

logger = logging.getLogger(__name__)

RECEIPT_TYPES = frozenset({39, 41})  # boleta electrónica, boleta exenta electrónica
MAX_TED = 4096  # a TED is about 1 KB; anything far larger is not one
MAX_TEXT = 120


def parse_ted(payload: str) -> ReceiptStamp | None:
    """The receipt fields of a TED, or None if it is not a receipt's TED or a field is missing or malformed."""
    if len(payload) > MAX_TED or "<TED" not in payload:
        return None
    dd = re.search(r"<DD>(.*?)</DD>", payload, re.S)
    if dd is None:
        return None
    body = dd.group(1)
    rut, kind, folio, issued, total = (_field(body, tag) for tag in ("RE", "TD", "F", "FE", "MNT"))
    if not (rut and kind and folio and issued and total):
        return None
    if not (re.fullmatch(r"\d{1,8}-[\dkK]", rut) and kind.isdigit() and folio.isdigit() and total.isdigit()):
        return None
    if int(kind) not in RECEIPT_TYPES:
        return None
    try:
        issued_on = date.fromisoformat(issued)
    except ValueError:
        return None
    return ReceiptStamp(
        issuer_rut=rut.upper(),
        document_type=int(kind),
        folio=int(folio),
        issued_on=issued_on,
        total=int(total),
        issuer_name=_field(body, "RS"),
        first_item=_field(body, "IT1"),
    )


def decode_stamp(content: bytes, file_format: str) -> ReceiptStamp | None:
    """The stamp from an image or the first page of a PDF; None if there is none or a library is missing."""
    try:
        import numpy as np
        import zxingcpp
        from PIL import Image
    except ImportError:
        return None
    try:
        if file_format == "image":
            image = Image.open(io.BytesIO(content)).convert("L")
        elif file_format == "pdf":
            image = _first_page(content)
            if image is None:
                return None
        else:
            return None
        for found in zxingcpp.read_barcodes(np.asarray(image), formats=zxingcpp.BarcodeFormat.PDF417):
            stamp = parse_ted(found.text)
            if stamp is not None:
                return stamp
    except Exception as exc:  # a broken image or code is a receipt without a stamp, never a failed import
        logger.info("no SII stamp decoded (%s)", type(exc).__name__)
    return None


def _first_page(content: bytes):
    try:
        import pymupdf  # the `ocr` extra, or `dev`
        from PIL import Image
    except ImportError:
        return None
    with pymupdf.open(stream=content, filetype="pdf") as pdf:
        if pdf.page_count == 0:
            return None
        pix = pdf[0].get_pixmap(dpi=200, colorspace=pymupdf.csGRAY)
        return Image.frombytes("L", (pix.width, pix.height), pix.samples)


def _field(body: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}>([^<]{{1,{MAX_TEXT * 2}}})</{tag}>", body)
    if m is None:
        return None
    return html.unescape(m.group(1)).strip()[:MAX_TEXT] or None
