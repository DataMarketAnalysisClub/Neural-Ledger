"""Azure AI Language PII detection ("Azure Language in Foundry Tools") as a PersonalDataDetector (ADR-028).

Off by default (NL_PII_DETECTOR=none). Turning it on sends the raw text of every imported statement line to
Microsoft. Synchronous detection is stateless (Microsoft stores nothing) and logging is opted out, but the text still
leaves the process, so SECURITY.md lists it. The domain rules run first either way and stay the floor.

Checked on Microsoft Learn on 2026-10-14 against REST API 2026-05-01 (GA):
- POST {endpoint}/language/:analyze-text?api-version=2026-05-01, with the key in the Ocp-Apim-Subscription-Key header.
- Body: {"kind": "PiiEntityRecognition", "parameters": {...}, "analysisInput": {"documents": [{"id", "language", "text"}]}}.
- Parameters: modelVersion "latest"; loggingOptOut true (its default is false in this version); an explicit piiCategories
  list, so only those come back; stringIndexType "UnicodeCodePoint", so offsets are Python string indices (the default
  counts graphemes).
- Every document says language "es": without it the service assumes English.
- Synchronous limits: 5 documents per request, 5,120 characters per document, 1 MB per request.
- Answer: results.documents[].entities[] (category, offset, length, confidenceScore) and results.errors[] per document.

Statement lines are packed into documents of at most 5,120 characters, one line per row, and entity offsets are mapped
back to their line. Any error (network, HTTP, a document error, a malformed answer) raises DetectorUnavailable, so the
rules alone redact and the import is flagged as degraded. Error messages carry the HTTP status and Azure's error codes,
never Azure's message (it can quote the text) and never the key. Standard library only (urllib), like the LLM adapters.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ....application.ports import DetectorUnavailable
from ....domain.privacy.redaction import Placeholder, Span

API_VERSION = "2026-05-01"
USER_AGENT = "neural-ledger/0.1"
LANGUAGE = "es"
MAX_DOCUMENT_CHARS = 5_120  # Azure counts graphemes; a code point count is never lower, so this stays within the limit
MAX_DOCUMENTS = 5
MAX_REQUEST_BYTES = 1_000_000

# The categories requested, and the placeholder each becomes. Not Organization: it would mask merchants (JUMBO, UBER)
# and break categorization. Not dates or URLs: they are not personal here.
CATEGORIES: Mapping[str, Placeholder] = {
    "Person": Placeholder.PERSON,
    "PhoneNumber": Placeholder.PHONE,
    "Email": Placeholder.EMAIL,
    "Address": Placeholder.ADDRESS,
    "BankAccountNumber": Placeholder.NUMBER,
    "CreditCardNumber": Placeholder.NUMBER,
    "InternationalBankingAccountNumber": Placeholder.NUMBER,
    "CLIdentityCardNumber": Placeholder.ID,
}


@dataclass(frozen=True, slots=True)
class _Piece:
    """A run of one input text inside a document: text[start : start + length] sits at `at` in the document."""

    text: int
    start: int
    length: int
    at: int


@dataclass(frozen=True, slots=True)
class _Document:
    text: str
    pieces: tuple[_Piece, ...]


class AzureLanguageDetector:
    name = "azure_language"

    def __init__(self, endpoint: str, api_key: str, *, timeout_s: float = 10.0) -> None:
        if not endpoint or not api_key:
            raise ValueError("AZURE_LANGUAGE_ENDPOINT and AZURE_LANGUAGE_API_KEY are required for NL_PII_DETECTOR=azure")
        self._url = f"{endpoint.rstrip('/')}/language/:analyze-text?api-version={API_VERSION}"
        self._api_key = api_key
        self._timeout_s = timeout_s

    def detect(self, texts: Sequence[str]) -> tuple[tuple[Span, ...], ...]:
        found: list[list[Span]] = [[] for _ in texts]
        for batch in _batches(_documents(texts)):
            for document, entities in zip(batch, self._analyze(batch), strict=True):
                for offset, length, category in entities:
                    for piece in document.pieces:
                        start, end = max(offset, piece.at), min(offset + length, piece.at + piece.length)
                        if start < end:  # an entity across two lines becomes one span on each
                            base = piece.start - piece.at
                            found[piece.text].append(Span(base + start, base + end, category))
        return tuple(tuple(spans) for spans in found)

    def _analyze(self, batch: Sequence[_Document]) -> list[list[tuple[int, int, Placeholder]]]:
        """(offset, length, placeholder) per entity, per document of the batch, in order."""
        body = _body(batch)
        request = urllib.request.Request(
            self._url,
            data=body,
            headers={"Ocp-Apim-Subscription-Key": self._api_key, "Content-Type": "application/json", "User-Agent": USER_AGENT},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise DetectorUnavailable(f"{self.name} returned HTTP {exc.code}{_error_code(exc)}") from exc
        except (OSError, ValueError) as exc:  # URLError and timeouts are OSError; a body that is not JSON is ValueError
            raise DetectorUnavailable(f"{self.name} request failed ({type(exc).__name__})") from exc
        try:
            return _entities(data, batch)
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
            raise DetectorUnavailable(f"{self.name} returned an unexpected answer ({type(exc).__name__})") from exc


def _documents(texts: Sequence[str]) -> list[_Document]:
    """Lines packed in order into documents of at most MAX_DOCUMENT_CHARS, one per row; a longer line is cut."""
    documents: list[_Document] = []
    rows: list[str] = []
    pieces: list[_Piece] = []
    size = 0
    for index, text in enumerate(texts):
        for start in range(0, len(text), MAX_DOCUMENT_CHARS):
            part = text[start : start + MAX_DOCUMENT_CHARS]
            if rows and size + 1 + len(part) > MAX_DOCUMENT_CHARS:
                documents.append(_Document("\n".join(rows), tuple(pieces)))
                rows, pieces, size = [], [], 0
            at = size + 1 if rows else 0
            rows.append(part)
            pieces.append(_Piece(index, start, len(part), at))
            size = at + len(part)
    if rows:
        documents.append(_Document("\n".join(rows), tuple(pieces)))
    return documents


def _batches(documents: Sequence[_Document]) -> list[list[_Document]]:
    """At most MAX_DOCUMENTS documents and MAX_REQUEST_BYTES of body per request."""
    batches: list[list[_Document]] = []
    for document in documents:
        if batches and len(batches[-1]) < MAX_DOCUMENTS and len(_body([*batches[-1], document])) <= MAX_REQUEST_BYTES:
            batches[-1].append(document)
        else:
            batches.append([document])
    return batches


def _body(batch: Sequence[_Document]) -> bytes:
    payload = {
        "kind": "PiiEntityRecognition",
        "parameters": {
            "modelVersion": "latest",
            "loggingOptOut": True,
            "piiCategories": list(CATEGORIES),
            "stringIndexType": "UnicodeCodePoint",
        },
        "analysisInput": {"documents": [{"id": str(i), "language": LANGUAGE, "text": d.text} for i, d in enumerate(batch, start=1)]},
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _entities(data: Any, batch: Sequence[_Document]) -> list[list[tuple[int, int, Placeholder]]]:
    results = data["results"]
    if results.get("errors"):
        codes = _codes(str(error["error"]["code"]) for error in results["errors"])
        raise DetectorUnavailable(f"azure_language could not analyze {len(results['errors'])} document(s){codes}")
    by_id = {str(document["id"]): document for document in results["documents"]}
    answers = []
    for i, document in enumerate(batch, start=1):
        entities = []
        for entity in by_id[str(i)]["entities"]:
            offset, length = entity["offset"], entity["length"]
            if not _inside(offset, length, len(document.text)):
                raise ValueError("an entity outside its document")
            category = CATEGORIES.get(entity["category"])
            if category is not None:  # only the categories requested; anything else is ignored, not guessed
                entities.append((offset, length, category))
        answers.append(entities)
    return answers


def _inside(offset: Any, length: Any, size: int) -> bool:
    return isinstance(offset, int) and isinstance(length, int) and 0 <= offset < offset + length <= size


def _error_code(exc: urllib.error.HTTPError) -> str:
    """Azure's error codes from the body or header ('Unauthorized', 'InvalidDocument'): never its message, which can quote the text."""
    codes = []
    try:
        error = json.loads(exc.read(2_000).decode("utf-8", errors="replace")).get("error") or {}
        codes = [str(error.get("code") or ""), str((error.get("innererror") or {}).get("code") or "")]
    except (OSError, ValueError, AttributeError):
        pass
    codes.append(exc.headers.get("x-ms-error-code", "") if exc.headers else "")
    return _codes(codes)


def _codes(codes) -> str:
    """' (A, B)' for the identifier-like codes only, so nothing that could quote a statement reaches a message."""
    known = list(dict.fromkeys(code for code in codes if code and code.replace("_", "").isalnum()))
    return f" ({', '.join(known)})" if known else ""
