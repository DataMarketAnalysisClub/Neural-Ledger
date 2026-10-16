"""Everything inbound adapters (HTTP, CLI) may call. Built by bootstrap, consumed by adapters."""

from __future__ import annotations

from dataclasses import dataclass

from .ports import Clock
from .services.tools import ToolRegistry
from .use_cases.actions import ActionUseCases
from .use_cases.audit import AuditUseCases
from .use_cases.chat import ChatUseCase
from .use_cases.financial import FinancialUseCases
from .use_cases.ledger import LedgerUseCases
from .use_cases.profile import ProfileUseCases
from .use_cases.statements import StatementUseCases


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
    persistence: str = "memory"  # memory | sqlite: `neural-ledger seed` refuses to seed a store that is gone at exit
