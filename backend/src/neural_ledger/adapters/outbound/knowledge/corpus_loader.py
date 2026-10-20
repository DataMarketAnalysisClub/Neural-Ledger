"""Concept cards from Markdown files (ADR-040): corpus/<lang>/<id>.md, a JSON header between `---` lines, then the body.

The format and the writing rules are in corpus/README.md. A bad card stops the load with a ValueError that
names the file: a card that silently disappears from the index looks exactly like a question with no answer.

`corpus_hash` names the corpus. Both knowledge bases carry it in their `name`, so every explanation records
which cards it was retrieved from, and the Chroma collection is rebuilt when any card changes.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

from ....domain.education.concepts import LANGUAGES, CardNumber, ConceptCard, Source

CORPUS = Path(__file__).with_name("corpus")
_DELIMITER = "---"


def load_cards(root: Path | None = None) -> tuple[ConceptCard, ...]:
    """Every card under root/<lang>/*.md, sorted by (lang, id). Raises ValueError naming the file on a bad card."""
    root = CORPUS if root is None else Path(root)
    cards = []
    for path in sorted(root.glob("*/*.md")):
        try:
            cards.append(_parse(path))
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from exc
    return tuple(sorted(cards, key=lambda c: (c.lang, c.id)))


def corpus_hash(cards: Iterable[ConceptCard]) -> str:
    """sha256 over every card's content in a canonical form (sorted keys, cards sorted by lang and id)."""
    canonical = sorted((dataclasses.asdict(c) for c in cards), key=lambda c: (c["lang"], c["id"]))
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _parse(path: Path) -> ConceptCard:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != _DELIMITER:
        raise ValueError("a card starts with a '---' line, then a JSON header")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == _DELIMITER), None)
    if end is None:
        raise ValueError("the JSON header is not closed by a '---' line")
    try:
        header = json.loads("\n".join(lines[1:end]))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON header: {exc}") from exc
    if not isinstance(header, dict):
        raise ValueError("the header must be a JSON object")
    body = "\n".join(lines[end + 1 :]).strip()

    for field in ("id", "lang", "title"):
        if not isinstance(header.get(field), str) or not header[field].strip():
            raise ValueError(f"missing or empty field {field!r}")
    if header["lang"] not in LANGUAGES:
        raise ValueError(f"lang {header['lang']!r} is not one of {LANGUAGES}")
    if header["id"] != path.stem:
        raise ValueError(f"id {header['id']!r} does not match the file name {path.stem!r}")
    if path.parent.name != header["lang"]:
        raise ValueError(f"lang {header['lang']!r} does not match the folder {path.parent.name!r}")
    if not body:
        raise ValueError("the body is empty")
    try:
        sources = tuple(Source(title=s["title"], url=s["url"], license=s["license"]) for s in header.get("sources", []))
        numbers = tuple(CardNumber(key=n["key"], value=n["value"], unit=n["unit"], meaning=n["meaning"]) for n in header.get("numbers", []))
    except (KeyError, TypeError) as exc:
        raise ValueError(f"a source needs title, url and license; a number needs key, value, unit and meaning ({exc!r})") from exc
    for n in numbers:
        if isinstance(n.value, bool) or not isinstance(n.value, int | float):
            raise ValueError(f"number {n.key!r} must have a numeric value")
    return ConceptCard(
        id=header["id"],
        lang=header["lang"],
        title=header["title"].strip(),
        body=body,
        aliases=_strings(header, "aliases"),
        tags=_strings(header, "tags"),
        related=_strings(header, "related"),
        sources=sources,
        numbers=numbers,
    )


def _strings(header: dict, field: str) -> tuple[str, ...]:
    values = header.get(field, [])
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise ValueError(f"{field!r} must be a list of strings")
    return tuple(values)
