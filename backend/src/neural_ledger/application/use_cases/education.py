"""Financial education by retrieval (ADR-039): explain a term from the team's concept cards.

Retrieval only. The cards are education, never advice: the envelope always carries the NOT_ADVICE caveat the
verifier enforces, card numbers are its facts, and card text reaches the model wrapped as untrusted data.
A knowledge base that cannot answer gives INSUFFICIENT_DATA, never an exception to the user.
"""

from __future__ import annotations

from dataclasses import replace

from ...domain.education.concepts import EDUCATION_VERSION, LANGUAGES, explanation_envelope
from ...domain.shared.envelope import Envelope
from ...domain.shared.hashing import canonical_json, sha256_hex
from ..ports import KnowledgeBase, KnowledgeBaseUnavailable, UserProfileStore

MAX_QUERY_CHARS = 300  # contracts/tools/search_financial_concepts.input.schema.json
MAX_K = 5
DEFAULT_K = 3
DEFAULT_LANG = "es"


class EducationUseCases:
    def __init__(self, knowledge_base: KnowledgeBase, min_score: float, profiles: UserProfileStore | None = None) -> None:
        if not 0 <= min_score <= 1:
            raise ValueError("min_score must be in [0, 1]")
        self._kb = knowledge_base
        self._min_score = min_score
        self._profiles = profiles

    @property
    def knowledge_base(self) -> str:
        return self._kb.name

    def _language(self, user_id: str, lang: str | None) -> str:
        if lang is not None:
            return lang
        profile = self._profiles.get(user_id) if self._profiles is not None else None
        if profile is not None and profile.language in LANGUAGES:
            return profile.language
        return DEFAULT_LANG

    def explain(self, user_id: str, query: object, lang: object = None, k: object = DEFAULT_K) -> Envelope[dict]:
        if not isinstance(query, str) or not query.strip():
            return Envelope.invalid("query", (), params_version=EDUCATION_VERSION, message="query must be a non-empty string")
        if len(query) > MAX_QUERY_CHARS:
            return Envelope.invalid("query", (), params_version=EDUCATION_VERSION, message=f"query must be at most {MAX_QUERY_CHARS} characters")
        if lang is not None and lang not in LANGUAGES:
            return Envelope.invalid("lang", LANGUAGES, params_version=EDUCATION_VERSION, message="lang must be es or en")
        if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= MAX_K:
            return Envelope.invalid("k", (), params_version=EDUCATION_VERSION, message=f"k must be an integer from 1 to {MAX_K}")
        language = self._language(user_id, lang)
        try:
            passages = self._kb.search(query.strip(), language, k)
        except KnowledgeBaseUnavailable:
            return Envelope.insufficient(
                ("knowledge_base",), params_version=EDUCATION_VERSION, message="the concept cards are unavailable right now"
            )
        envelope = explanation_envelope(passages[:k], self._kb.name, self._min_score)
        if not envelope.ok:
            return envelope
        ids = [c["id"] for c in envelope.data["concepts"]] if envelope.data else []
        snapshot = sha256_hex(canonical_json({"kb": self._kb.name, "version": EDUCATION_VERSION, "lang": language, "cards": ids}))
        return replace(envelope, snapshot_id=f"edu_{snapshot[:16]}")
