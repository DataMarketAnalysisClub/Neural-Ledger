"""ASGI entrypoint: uvicorn neural_ledger.bootstrap.asgi:app"""

from ..adapters.inbound.http.app import create_app
from ..adapters.inbound.http.rate_limit import DEFAULT_LIMITS
from .config import Settings
from .container import build_services

_settings = Settings.from_env()
app = create_app(
    build_services(_settings),
    cors_origins=_settings.cors_origins,
    rate_limits=DEFAULT_LIMITS if _settings.rate_limit else (),
)
