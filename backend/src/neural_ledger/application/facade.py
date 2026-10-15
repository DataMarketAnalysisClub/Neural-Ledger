"""Everything inbound adapters (HTTP, CLI) may call. Built by bootstrap, consumed by adapters."""

from __future__ import annotations

from dataclasses import dataclass

from .ports import Clock
from .services.tools import ToolRegistry
from .use_cases.accounts import AccountUseCases
from .use_cases.actions import ActionUseCases
from .use_cases.audit import AuditUseCases
from .use_cases.chat import ChatUseCase
from .use_cases.financial import FinancialUseCases
from .use_cases.ledger import LedgerUseCases
from .use_cases.profile import ProfileEditing, ProfileUseCases
from .use_cases.statements import StatementUseCases


@dataclass(frozen=True, slots=True)
class AuthConfig:
    """How inbound adapters identify the user (NL_AUTH).

    demo: the X-User-Id header or default_user, read-only profiles, no auth routes (local and recorded demos).
    accounts: an nl_session cookie only; X-User-Id is rejected and unsafe requests must come from app_origins.
    """

    mode: str = "demo"  # demo | accounts
    app_origins: tuple[str, ...] = ()  # exact origins allowed to send unsafe requests in accounts mode
    cookie_secure: str = "auto"  # auto (https or X-Forwarded-Proto=https) | true | false
    demo_personas: tuple[str, ...] = ()  # personas a demo session may open; empty = demo sessions disabled

    @property
    def accounts(self) -> bool:
        return self.mode == "accounts"


@dataclass(frozen=True)
class ApplicationServices:
    financial: FinancialUseCases
    actions: ActionUseCases
    profiles: ProfileUseCases
    audit: AuditUseCases
    statements: StatementUseCases
    ledger: LedgerUseCases
    chat: ChatUseCase
    registry: ToolRegistry
    default_user: str
    mode: str  # "offline" or "live": shown in /health so the demo never runs in the wrong mode
    language_model: str
    decision_chain: tuple[str, ...]
    pii_detector: str  # after the redaction rules on imported statements; anything but "none" sends their text out (ADR-028)
    clock: Clock | None = None  # exposed as /health server_time so UI timers follow the API clock (fixed in demos)
    auth: AuthConfig = AuthConfig()
    accounts: AccountUseCases | None = None  # accounts mode only
    profile_editing: ProfileEditing | None = None  # accounts mode only: profile writes are user-only HTTP flows
