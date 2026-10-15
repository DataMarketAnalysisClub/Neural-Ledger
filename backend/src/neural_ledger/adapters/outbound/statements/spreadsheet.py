"""Spreadsheets (.xlsx) as rows of cell text, with the standard library only.

A bank's Excel export already is the table: reading it is a zip and a few XML parts, so it never
goes near the PDF or OCR path (no pdfplumber, no rasterizing, no EasyOCR):

    bytes ──► is_xlsx (zip magic + xl/workbook.xml, never the file name)
          ──► read_workbook ──► Sheet per worksheet, in workbook order (rows of cell text)
          ──► SheetBank.parse(sheets) ──► BankStatement

Cells keep the text Excel stores: shared and inline strings as written, numbers as their raw
value ('8.22', '-120990', no thousands separators), booleans as '0'/'1'. Dates stored as serial
numbers stay numbers; the layouts seen so far write dates as text.

The file is untrusted: entries and uncompressed size are capped (zip bombs), and an XML part with
a DOCTYPE is refused (entity expansion). Legacy binary .xls is recognized only to say so.
"""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree

from .ocr_tabular import TableError, norm_text

MAX_ENTRIES = 500
MAX_PART_BYTES = 20 * 1024 * 1024  # one XML part, uncompressed
MAX_TOTAL_BYTES = 60 * 1024 * 1024  # everything declared in one workbook

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_CELL_REF = re.compile(r"^([A-Z]{1,3})(\d+)$")


@dataclass(frozen=True, slots=True)
class Sheet:
    name: str
    rows: tuple[tuple[str, ...], ...]  # non-empty rows in order; each dense from column A ('' = empty cell)

    @property
    def text(self) -> str:
        """Non-empty cells, one line per row; enough to recognize which bank exported it."""
        return "\n".join(" ".join(c for c in row if c.strip()) for row in self.rows)

    def find(self, label: str) -> tuple[int, int] | None:
        """(row, column) of the first cell whose normalized text is `label` normalized."""
        wanted = norm_text(label)
        for r, row in enumerate(self.rows):
            for c, cell in enumerate(row):
                if cell and norm_text(cell) == wanted:
                    return r, c
        return None

    def right_of(self, label: str) -> str | None:
        """The cell right of `label` on its row ('Saldo inicial:' → '$100.000'); None if `label` is absent."""
        found = self.find(label)
        if found is None:
            return None
        r, c = found
        return self.rows[r][c + 1] if c + 1 < len(self.rows[r]) else ""

    def below(self, label: str) -> str | None:
        """The cell under `label` ('Total Cargos' → '95.500 CLP')."""
        found = self.find(label)
        if found is None or found[0] + 1 >= len(self.rows):
            return None
        row = self.rows[found[0] + 1]
        return row[found[1]] if found[1] < len(row) else None


def is_xlsx(content: bytes) -> bool:
    if not content.startswith(b"PK\x03\x04"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            return "xl/workbook.xml" in archive.namelist()
    except zipfile.BadZipFile:
        return False


def is_legacy_xls(content: bytes) -> bool:
    return content.startswith(_OLE2)


def read_workbook(content: bytes) -> list[Sheet]:
    """Every worksheet, in the workbook's tab order."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise TableError(f"cannot open the spreadsheet: {exc}") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ENTRIES:
            raise TableError("the spreadsheet has too many parts")
        if sum(i.file_size for i in infos) > MAX_TOTAL_BYTES:
            raise TableError("the spreadsheet is too large once uncompressed")
        names = {i.filename for i in infos}
        shared = _shared_strings(archive) if "xl/sharedStrings.xml" in names else []
        sheets = [Sheet(name, _rows(_xml(archive, path), shared)) for name, path in _sheet_paths(archive, names)]
    if not sheets:
        raise TableError("the spreadsheet has no worksheets")
    return sheets


def _xml(archive: zipfile.ZipFile, path: str) -> ElementTree.Element:
    try:
        with archive.open(path) as part:
            data = part.read(MAX_PART_BYTES + 1)  # a declared size can lie; never read past the cap
    except KeyError as exc:
        raise TableError(f"the spreadsheet is missing {path}") from exc
    except (zipfile.BadZipFile, OSError, NotImplementedError) as exc:  # bad CRC, truncated, unknown compression
        raise TableError(f"cannot read {path}: {exc}") from exc
    if len(data) > MAX_PART_BYTES:
        raise TableError(f"{path} is too large")
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise TableError(f"{path} declares a DOCTYPE or entities, which a spreadsheet never needs")
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise TableError(f"{path} is not valid XML: {exc}") from exc


def _sheet_paths(archive: zipfile.ZipFile, names: set[str]) -> list[tuple[str, str]]:
    workbook = _xml(archive, "xl/workbook.xml")
    targets: dict[str, str] = {}
    if "xl/_rels/workbook.xml.rels" in names:
        for rel in _xml(archive, "xl/_rels/workbook.xml.rels").iter(f"{_PKG_REL}Relationship"):
            target = rel.get("Target", "")
            # Relative to xl/, or absolute from the package root ('/xl/worksheets/sheet1.xml').
            path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
            targets[rel.get("Id", "")] = path
    found = []
    for sheet in workbook.iter(f"{_MAIN}sheet"):
        path = targets.get(sheet.get(f"{_REL}id", ""))
        if path in names:
            found.append((sheet.get("name", ""), path))
    if not found:  # no usable relationships: fall back to the conventional part names
        found = [(posixpath.basename(n), n) for n in sorted(names) if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)]
    return found


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    # Rich text runs (<r><t>) join into one string; phonetic hints (<rPh>) are not text.
    return ["".join(t.text or "" for t in _texts(si)) for si in _xml(archive, "xl/sharedStrings.xml").iter(f"{_MAIN}si")]


def _texts(node: ElementTree.Element):
    for child in node:
        if child.tag == f"{_MAIN}t":
            yield child
        elif child.tag == f"{_MAIN}r":
            yield from (t for t in child if t.tag == f"{_MAIN}t")


def _rows(root: ElementTree.Element, shared: list[str]) -> tuple[tuple[str, ...], ...]:
    rows = []
    for row in root.iter(f"{_MAIN}row"):
        cells: dict[int, str] = {}
        for position, cell in enumerate(row.iter(f"{_MAIN}c")):
            match = _CELL_REF.match(cell.get("r", ""))
            value = _value(cell, shared)
            if value:
                cells[_column(match.group(1)) if match else position] = value
        if cells:
            rows.append(tuple(cells.get(c, "") for c in range(max(cells) + 1)))
    return tuple(rows)


def _value(cell: ElementTree.Element, shared: list[str]) -> str:
    kind = cell.get("t", "n")
    if kind == "inlineStr":
        inline = cell.find(f"{_MAIN}is")
        return "".join(t.text or "" for t in _texts(inline)) if inline is not None else ""
    v = cell.find(f"{_MAIN}v")
    raw = v.text if v is not None and v.text is not None else ""
    if kind == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError) as exc:
            raise TableError(f"cell {cell.get('r')} points at a shared string that does not exist") from exc
    if kind == "e":  # #N/A, #REF!: not a value
        return ""
    return raw


def _column(letters: str) -> int:
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index - 1
