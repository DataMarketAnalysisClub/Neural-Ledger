"""KnowledgeBase on ChromaDB with a multilingual embedding model (the `rag` extra), ADR-039.

One document per card: title, aliases and body, embedded by `paraphrase-multilingual-MiniLM-L12-v2` (384
dimensions), so a Spanish question finds an English card and the other way round. The model runs on ONNX
Runtime through fastembed: no torch, and the weights are downloaded once into NL_KB_DIR/models.

The index is built at first use, never shipped: the collection is named after the corpus hash and the model,
so a changed card or another model gets a fresh collection, and the old ones are dropped.
Where the index lives: `url` (NL_KB_URL) = a Chroma server in its own container, reached over HTTP; otherwise
`path` (NL_KB_DIR) = an embedded index on disk; `path=None` keeps it in memory (tests, one-off evaluations).
Embedding always happens here, never in the server: the server only stores and searches vectors, and the model's
weights are cached under `path`.

Scores are 1 - cosine distance, floored at 0: a passage pointing the other way from the question scores 0.
Cards in the asked language come first; when none of them scores above 0, the other language answers.

Every failure (the extra not installed, the model not downloadable offline, a broken index) becomes
KnowledgeBaseUnavailable, so the fallback (lexical) answers instead of the chat failing.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ....application.ports import KnowledgeBaseUnavailable
from ....domain.education.concepts import LANGUAGES, ConceptCard, Passage
from .corpus_loader import corpus_hash

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_PREFIX = "concepts-"

EmbeddingFunction = Callable[[Sequence[str]], Sequence[Sequence[float]]]


def fastembed_embedding(model: str, cache_dir: str | None = None) -> EmbeddingFunction:
    """Texts -> vectors with fastembed (ONNX Runtime). The model is loaded on the first call."""
    from fastembed import TextEmbedding

    embedder = TextEmbedding(model_name=model, cache_dir=cache_dir)
    return lambda texts: [vector.tolist() for vector in embedder.embed(list(texts))]


def document_text(card: ConceptCard) -> str:
    return "\n".join((card.title, ", ".join(card.aliases), card.body))


class ChromaKnowledgeBase:
    def __init__(
        self,
        cards: Sequence[ConceptCard],
        path: str | None,
        model: str = DEFAULT_MODEL,
        embedding_function: EmbeddingFunction | None = None,
        url: str | None = None,
    ) -> None:
        self._cards = {(c.lang, c.id): c for c in cards}
        self._path = path
        self._url = url
        self._model = model
        self._embed = embedding_function
        digest = corpus_hash(cards)
        self.name = f"chroma/{model}/{digest[:8]}"
        self._collection_name = f"{_PREFIX}{digest[:16]}-{hashlib.sha256(model.encode()).hexdigest()[:8]}"
        self._collection: Any = None
        self._lock = threading.Lock()

    def search(self, query: str, lang: str, k: int) -> Sequence[Passage]:
        if not query.strip() or k <= 0 or not self._cards:
            return ()
        try:
            collection = self._index()
            vector = self._embedder()([query])[0]
            passages: list[Passage] = []
            if lang in LANGUAGES:
                passages = self._query(collection, vector, k, {"lang": lang})
            return tuple(passages or self._query(collection, vector, k, None))
        except KnowledgeBaseUnavailable:
            raise
        except Exception as exc:  # the extra, the model download, the index: any failure hands over to the fallback
            raise KnowledgeBaseUnavailable(f"chroma knowledge base unavailable: {type(exc).__name__}: {exc}") from exc

    def _query(self, collection: Any, vector: Sequence[float], k: int, where: dict | None) -> list[Passage]:
        result = collection.query(query_embeddings=[list(vector)], n_results=min(k, len(self._cards)), where=where)
        passages = []
        for meta, distance in zip(result["metadatas"][0], result["distances"][0]):
            score = max(0.0, min(1.0, 1.0 - float(distance)))
            card = self._cards.get((meta["lang"], meta["id"]))
            if card is not None and score > 0:
                passages.append(Passage(card, card.body, score))
        return sorted(passages, key=lambda p: (-p.score, p.card.id))

    def _embedder(self) -> EmbeddingFunction:
        if self._embed is None:
            try:
                cache = str(Path(self._path) / "models") if self._path else None
                self._embed = fastembed_embedding(self._model, cache)
            except ImportError as exc:
                raise KnowledgeBaseUnavailable("the chroma knowledge base needs the `rag` extra (pip install 'neural-ledger[rag]')") from exc
        return self._embed

    def _index(self) -> Any:
        with self._lock:
            if self._collection is None:
                try:
                    import chromadb
                except ImportError as exc:
                    raise KnowledgeBaseUnavailable("the chroma knowledge base needs the `rag` extra (pip install 'neural-ledger[rag]')") from exc
                client = self._client(chromadb)
                collection = client.get_or_create_collection(self._collection_name, metadata={"hnsw:space": "cosine"}, embedding_function=None)
                if collection.count() != len(self._cards):
                    self._fill(collection)
                if self._url is not None or self._path is not None:
                    self._drop_stale(client)
                self._collection = collection
            return self._collection

    def _client(self, chromadb: Any) -> Any:
        if self._url is not None:
            parsed = urlparse(self._url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                raise KnowledgeBaseUnavailable(f"NL_KB_URL must be an http(s) URL, got {self._url!r}")
            port = parsed.port or (443 if parsed.scheme == "https" else 8000)
            return chromadb.HttpClient(host=parsed.hostname, port=port, ssl=parsed.scheme == "https")
        return chromadb.EphemeralClient() if self._path is None else chromadb.PersistentClient(path=self._path)

    def _fill(self, collection: Any) -> None:
        cards = list(self._cards.values())
        ids = [f"{c.lang}/{c.id}" for c in cards]
        existing = collection.get()["ids"]
        if existing:
            collection.delete(ids=existing)  # a half-built index from an interrupted start
        collection.add(
            ids=ids,
            embeddings=[list(v) for v in self._embedder()([document_text(c) for c in cards])],
            documents=[document_text(c) for c in cards],
            metadatas=[{"id": c.id, "lang": c.lang, "tags": ",".join(c.tags)} for c in cards],
        )

    def _drop_stale(self, client: Any) -> None:
        """Collections of an older corpus or model, so NL_KB_DIR does not grow with every card edit."""
        for listed in client.list_collections():
            name = listed if isinstance(listed, str) else listed.name
            if name.startswith(_PREFIX) and name != self._collection_name:
                client.delete_collection(name)
