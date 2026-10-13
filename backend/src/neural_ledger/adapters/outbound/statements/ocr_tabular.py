"""Tables from PDFs (text layer or scanned) and photos, with a confidence per cell.

Adapted from SIT's `ocr_tabular` (Caja → Box, Tabla → Table, reconstruir → rebuild), with the
changes bank statements need:

    bytes ──► detect_format (magic bytes, never the file name)
               ├─ image ─────────────────────────────────────────────► OCR ─┐
               └─ pdf ──► text layer ≥ 20 chars?                            │
                            ├─ yes ─► pdfplumber words, every page ─────────┤ boxes
                            └─ no  ─► rasterize every page at 300 dpi ► OCR ┘
    boxes + TableSpec (from the Bank) ──► rebuild ──► Table per page

- Every page, not only the first: statements run over several pages.
- The text layer goes through the same box pipeline as OCR (confidence 1.0), instead of
  pdfplumber's table finder, which merges a whole column into one cell on statements.
- The header can span two lines ("CHEQUES / Y CARGOS"); header words are grouped into
  columns by horizontal overlap, as in the original.
- Data columns are bounded by the header's left edges, not by overlap: amounts are
  right-aligned and often sit outside their header word's width.
- The table ends at a stop marker ("MENSAJES"), so page footers never become rows.
- Straight pages (PDFs) group rows by y across all columns. Only photos use the original
  per-column grouping with order-preserving alignment, which survives page curvature.

Heavy libraries (pdfplumber, pymupdf, easyocr) are imported lazily: install the `pdf` extra
for text-layer PDFs and the `ocr` extra for scans and photos.
"""

from __future__ import annotations

import io
import re
import statistics
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

MINIMUM_TEXT_LAYER = 20  # characters for a PDF to count as having a text layer
RASTER_DPI = 300  # what EasyOCR needs not to lose thousands separators


class TableError(Exception):
    """The content could not be read as the expected table."""


class MissingDependency(TableError):
    """A library or model weights this file needs are not installed. Not the file's fault."""


class HeaderNotFound(TableError):
    """The page has no table of the expected layout (e.g. a trailing page with only notices)."""


@dataclass(frozen=True, slots=True)
class Box:
    x0: float
    x1: float
    y0: float
    y1: float
    text: str
    confidence: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass(frozen=True, slots=True)
class Page:
    number: int  # from 1
    boxes: tuple[Box, ...]
    source: str  # text | ocr
    straight: bool  # rows are horizontal lines (PDF), as opposed to a photo that may curve

    @property
    def text(self) -> str:
        """Plain text in reading order; enough to recognize which bank printed it."""
        if not self.boxes:
            return ""
        rows = _group_y(list(self.boxes), _tolerance(self.boxes))
        return "\n".join(" ".join(b.text for b in sorted(row, key=lambda b: b.x0)) for row in rows)


@dataclass(frozen=True, slots=True)
class TableSpec:
    """How to find one bank's table on a page. Tokens are compared after `norm_text`."""

    header_required: frozenset[str]  # all must appear in the header's first line
    header_tokens: frozenset[str]  # every word a header line may contain (second lines included)
    stop_markers: tuple[str, ...] = ()  # a line starting with one of these ends the table


@dataclass
class Table:
    """Rows of cell text in page order, without losing empty columns.

    `rows` holds the preamble (rows above the header, one cell per word), the header and the
    data, in that order; `header_index` points at the header. `confidences` is parallel to
    `rows` and exists only on the OCR path (None for a text layer).
    """

    rows: list[list[str]]
    header_index: int
    source: str  # text | ocr
    page: int
    confidences: list[list[float]] | None = None

    @property
    def header(self) -> list[str]:
        return self.rows[self.header_index]

    @property
    def data(self) -> list[list[str]]:
        return self.rows[self.header_index + 1 :]

    @property
    def data_confidences(self) -> list[list[float]] | None:
        return None if self.confidences is None else self.confidences[self.header_index + 1 :]

    @property
    def preamble(self) -> list[str]:
        """Lines above the header, verbatim, one string per line."""
        return [" ".join(c for c in row if c).strip() for row in self.rows[: self.header_index]]


# ---------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------
_MOJIBAKE_MARKS = "├┬�"


def norm_text(s: str) -> str:
    """Repair CP850 mojibake, strip accents, lowercase, non-alphanumerics to spaces."""
    s = str(s or "")
    if any(c in s for c in _MOJIBAKE_MARKS):
        try:
            s = s.encode("cp850").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------
# EasyOCR reader
# ---------------------------------------------------------------------
_readers: dict[tuple, object] = {}


def ocr_reader(languages: Sequence[str] = ("es",), gpu: bool = False, model_dir: str | None = None, download: bool = False):
    """Built once per configuration: loading the weights takes seconds. Never downloads by
    default; run `prepare_models` once (with network) or ship the weights in `model_dir`."""
    key = (tuple(languages), gpu, model_dir)
    if key not in _readers:
        try:
            import easyocr
        except ImportError as exc:
            raise MissingDependency("this file needs OCR; install the backend's `ocr` extra") from exc
        kwargs = {"gpu": gpu, "verbose": False, "download_enabled": download}
        if model_dir:
            kwargs["model_storage_directory"] = model_dir
        try:
            _readers[key] = easyocr.Reader(list(languages), **kwargs)
        except FileNotFoundError as exc:
            raise MissingDependency("EasyOCR weights are missing; run prepare_models() once with network access") from exc
    return _readers[key]


def prepare_models(languages: Sequence[str] = ("es",), model_dir: str | None = None) -> None:
    """Download the CRAFT detector and the latin recognizer (~100 MB). Network once, offline after."""
    ocr_reader(languages, gpu=False, model_dir=model_dir, download=True)


def recognize(image, **reader_options) -> list[Box]:
    try:
        import numpy as np
    except ImportError as exc:
        raise MissingDependency("this file needs OCR; install the backend's `ocr` extra") from exc

    boxes = []
    for points, text, confidence in ocr_reader(**reader_options).readtext(np.asarray(image), detail=1):
        text = str(text).strip()
        if not text:
            continue
        xs = [float(p[0]) for p in points]
        ys = [float(p[1]) for p in points]
        boxes.append(Box(min(xs), max(xs), min(ys), max(ys), text, float(confidence)))
    return boxes


# ---------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------
def detect_format(content: bytes) -> str | None:
    """'pdf' | 'image' from the magic bytes, or None."""
    head = content[:16]
    if head.startswith(b"%PDF"):
        return "pdf"
    if (
        head.startswith(b"\xff\xd8\xff")
        or head.startswith(b"\x89PNG")
        or head[:4] in (b"II*\x00", b"MM\x00*")
        or (head[:4] == b"RIFF" and head[8:12] == b"WEBP")
        or head.startswith(b"BM")
    ):
        return "image"
    return None


def read_pages(content: bytes, **reader_options) -> list[Page]:
    """Every page as boxes. `reader_options` go to EasyOCR (languages, gpu, model_dir)."""
    kind = detect_format(content)
    if kind == "pdf":
        return _pdf_pages(content, **reader_options)
    if kind == "image":
        try:
            from PIL import Image, UnidentifiedImageError
        except ImportError as exc:
            raise MissingDependency("this file needs OCR; install the backend's `ocr` extra") from exc
        try:
            image = Image.open(io.BytesIO(content)).convert("RGB")
        except (UnidentifiedImageError, OSError) as exc:
            raise TableError(f"cannot open the image: {exc}") from exc
        return [Page(1, tuple(recognize(image, **reader_options)), "ocr", straight=False)]
    raise TableError("unsupported format: expected a PDF or an image")


def _pdf_pages(content: bytes, **reader_options) -> list[Page]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise MissingDependency("reading PDFs needs the backend's `pdf` extra") from exc
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            words = [page.extract_words(x_tolerance=1.5) for page in pdf.pages]
    except Exception as exc:  # pdfplumber raises many unrelated types on broken files
        raise TableError(f"cannot open the pdf: {exc}") from exc
    if sum(len(w["text"]) for page in words for w in page) >= MINIMUM_TEXT_LAYER:
        return [
            Page(n, tuple(Box(w["x0"], w["x1"], w["top"], w["bottom"], w["text"], 1.0) for w in page), "text", straight=True)
            for n, page in enumerate(words, start=1)
        ]
    return [Page(n, tuple(recognize(image, **reader_options)), "ocr", straight=True) for n, image in enumerate(rasterize(content), start=1)]


def rasterize(content: bytes, dpi: int = RASTER_DPI):
    """Every page of a PDF as a PIL image."""
    try:
        import pymupdf
        from PIL import Image
    except ImportError as exc:
        raise MissingDependency("this scanned PDF needs OCR; install the backend's `ocr` extra") from exc

    with pymupdf.open(stream=content, filetype="pdf") as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            yield Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


# ---------------------------------------------------------------------
# Rebuild
# ---------------------------------------------------------------------
def rebuild(page: Page, spec: TableSpec) -> Table:
    """Boxes → Table. Pure: testable with synthetic boxes and no OCR installed."""
    boxes = list(page.boxes)
    if not boxes:
        raise TableError(f"page {page.number} has no text")
    tol = _tolerance(boxes)
    coarse = _group_y(boxes, tol)

    required = {norm_text(t) for t in spec.header_required}
    allowed = {norm_text(t) for t in spec.header_tokens} | required
    start = next((i for i, row in enumerate(coarse) if required <= {norm_text(b.text) for b in row}), None)
    if start is None:
        raise HeaderNotFound(f"page {page.number}: header not found")
    end = start + 1
    while end < len(coarse) and all(norm_text(b.text) in allowed for b in coarse[end]):
        end += 1
    markers = tuple(norm_text(m) for m in spec.stop_markers)
    stop = next((k for k in range(end, len(coarse)) if markers and _line_text(coarse[k]).startswith(markers)), len(coarse))

    header_boxes = [b for row in coarse[start:end] for b in row]
    spans = _columns(header_boxes)
    edges = [x0 - tol for x0, _ in spans]

    rows: list[list[str]] = []
    confs: list[list[float]] = []
    for row in coarse[:start]:
        ordered = sorted(row, key=lambda b: b.x0)
        rows.append([b.text for b in ordered])
        confs.append([b.confidence for b in ordered])

    header = [""] * len(spans)
    header_conf = [0.0] * len(spans)
    for b in sorted(header_boxes, key=lambda b: (b.cy, b.x0)):
        j = _column_by_overlap(b, spans)
        if j is not None:
            header[j] = f"{header[j]} {b.text}".strip()
            header_conf[j] = max(header_conf[j], b.confidence)
    rows.append(header)
    confs.append(header_conf)

    data = [b for row in coarse[end:stop] for b in row]
    cells, cell_confs = (_straight_rows if page.straight else _curved_rows)(data, edges, tol)
    rows.extend(cells)
    confs.extend(cell_confs)
    return Table(rows=rows, header_index=start, source=page.source, page=page.number, confidences=confs if page.source == "ocr" else None)


def _tolerance(boxes: Sequence[Box]) -> float:
    return max(statistics.median(b.height for b in boxes) / 2, 1.0)


def _line_text(row: list[Box]) -> str:
    return norm_text(" ".join(b.text for b in sorted(row, key=lambda b: b.x0)))


def _column_by_edges(box: Box, edges: list[float]) -> int:
    """The last column whose left edge is at or before the box's left edge."""
    j = 0
    for k, edge in enumerate(edges):
        if box.x0 >= edge:
            j = k
    return j


def _fill(row_boxes: list[Box], edges: list[float]) -> tuple[list[str], list[float]]:
    by_col: list[list[Box]] = [[] for _ in edges]
    for b in row_boxes:
        by_col[_column_by_edges(b, edges)].append(b)
    texts = [" ".join(b.text for b in sorted(col, key=lambda b: b.x0)) for col in by_col]
    # min: the worst-read box sets the cell's confidence.
    confs = [min((b.confidence for b in col), default=0.0) for col in by_col]
    return texts, confs


def _straight_rows(data: list[Box], edges: list[float], tol: float) -> tuple[list[list[str]], list[list[float]]]:
    cells, confs = [], []
    for row in _group_y(data, tol):
        texts, row_confs = _fill(row, edges)
        cells.append(texts)
        confs.append(row_confs)
    return cells, confs


def _curved_rows(data: list[Box], edges: list[float], tol: float) -> tuple[list[list[str]], list[list[float]]]:
    """Group within each column (no drift there), then align columns by order, not by y."""
    n_col = len(edges)
    per_col: list[list[Box]] = [[] for _ in range(n_col)]
    for b in data:
        per_col[_column_by_edges(b, edges)].append(b)
    groups = [_group_y(own, tol) for own in per_col]
    reference = max(range(n_col), key=lambda j: len(groups[j]))
    n_rows = len(groups[reference])
    y_ref = [_center(g) for g in groups[reference]]
    cells = [[""] * n_col for _ in range(n_rows)]
    confs = [[0.0] * n_col for _ in range(n_rows)]
    for j in range(n_col):
        for k, i in enumerate(_align(y_ref, [_center(g) for g in groups[j]])):
            ordered = sorted(groups[j][k], key=lambda b: b.x0)
            cells[i][j] = " ".join(b.text for b in ordered)
            confs[i][j] = min(b.confidence for b in ordered)
    return cells, confs


def _group_y(boxes: list[Box], tol: float) -> list[list[Box]]:
    """Group by y centroid, sequentially, against the running group mean."""
    groups: list[list[Box]] = []
    for box in sorted(boxes, key=lambda b: b.cy):
        if groups and abs(box.cy - _center(groups[-1])) <= tol:
            groups[-1].append(box)
        else:
            groups.append([box])
    return groups


def _center(group: list[Box]) -> float:
    return sum(b.cy for b in group) / len(group)


def _columns(boxes: list[Box]) -> list[tuple[float, float]]:
    """Columns by horizontal overlap (union-find over intervals), left to right.

    Overlap is what joins a header's second line ("Y CARGOS") to its first ("CHEQUES").
    """
    n = len(boxes)
    parent = list(range(n))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    order = sorted(range(n), key=lambda i: boxes[i].x0)
    for a in range(n):
        for b in range(a + 1, n):
            i, j = order[a], order[b]
            if boxes[j].x0 >= boxes[i].x1:
                continue
            ri, rj = root(i), root(j)
            if ri != rj:
                parent[rj] = ri

    spans: dict[int, list[float]] = {}
    for i, box in enumerate(boxes):
        r = root(i)
        if r in spans:
            spans[r][0] = min(spans[r][0], box.x0)
            spans[r][1] = max(spans[r][1], box.x1)
        else:
            spans[r] = [box.x0, box.x1]
    return [(a, b) for a, b in sorted(spans.values())]


def _column_by_overlap(box: Box, spans: list[tuple[float, float]]) -> int | None:
    best, best_j = 0.0, None
    for j, (x0, x1) in enumerate(spans):
        overlap = min(box.x1, x1) - max(box.x0, x0)
        if overlap > best:
            best, best_j = overlap, j
    return best_j


def _align(reference: list[float], target: list[float]) -> list[int]:
    """Assign each target group to a reference row, preserving order and minimizing total
    vertical distance. On a curved page distances lie; the sequence does not."""
    n, m = len(reference), len(target)
    if m == 0:
        return []
    if m > n:
        return list(range(m))
    inf = float("inf")
    cost = [[inf] * (m + 1) for _ in range(n + 1)]
    came = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        cost[i][0] = 0.0
    for i in range(1, n + 1):
        for j in range(1, min(i, m) + 1):
            best, origin = cost[i - 1][j], 0  # 0 = leave the reference row empty
            c = cost[i - 1][j - 1] + abs(reference[i - 1] - target[j - 1])
            if c < best:
                best, origin = c, 1  # 1 = assign
            cost[i][j], came[i][j] = best, origin
    assignment = [0] * m
    i, j = n, m
    while j > 0:
        if came[i][j] == 1:
            assignment[j - 1] = i - 1
            i -= 1
            j -= 1
        else:
            i -= 1
    return assignment
