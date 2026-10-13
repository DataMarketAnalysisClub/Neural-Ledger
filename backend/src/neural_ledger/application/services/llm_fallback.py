"""Language-model fallback: try the primary provider, fall back to the next one (scripted last)."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from ..conversation import ModelRequest, ModelTurn
from ..ports import LanguageModel, LanguageModelUnavailable

logger = logging.getLogger(__name__)


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
                # A silent fallback looks exactly like a working provider, so always say why.
                logger.warning("language model %s unavailable, trying the next one: %s", model.name, exc)
                last_error = exc
        raise LanguageModelUnavailable(f"all language models failed: {last_error}")
