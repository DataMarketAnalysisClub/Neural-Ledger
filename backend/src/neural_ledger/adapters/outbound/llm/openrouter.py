"""OpenRouter (one OpenAI-compatible API in front of many providers and models).

`require_parameters` makes OpenRouter route only to providers that support every parameter we send,
so a provider that would silently ignore `tools` is never chosen.
No temperature is sent by default: Claude 5.x endpoints do not support it, and with `require_parameters`
that would leave no endpoint to route to. Model ids look like "anthropic/claude-haiku-5.5"; the public catalog is https://openrouter.ai/api/v1/models.
"""

from __future__ import annotations

from .openai_compatible import OpenAICompatibleLanguageModel

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterLanguageModel(OpenAICompatibleLanguageModel):
    provider = "openrouter"
    key_variable = "OPENROUTER_API_KEY"
    default_base_url = DEFAULT_BASE_URL
    extra_body = {"provider": {"require_parameters": True}}
