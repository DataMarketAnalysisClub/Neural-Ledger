"""Language-model fallback: try the primary provider, fall back to the next one (scripted last)."""

from __future__ import annotations

from collections.abc import Sequence

from ..conversation import ModelRequest, ModelTurn
from ..ports import LanguageModel, LanguageModelUnavailable


class FallbackLanguageModel:
    def __init__(self, models: Sequence[LanguageModel]) -> None:
        if not models:
            raise ValueError("at least one language model is required")
        self._models = tuple(models)
        self.name = "+".join(m.name for m in self._models)

    def respond(self, request: ModelRequest) -> ModelTurn:
        last_error: Exception | None = None
        for model in self._models:
            try:
                return model.respond(request)
            except LanguageModelUnavailable as exc:
                last_error = exc
        raise LanguageModelUnavailable(f"all language models failed: {last_error}")
