"""Everything inbound adapters (HTTP, CLI) may call. Built by bootstrap, consumed by adapters."""

from __future__ import annotations

from dataclasses import dataclass

from .services.tools import ToolRegistry
from .use_cases.actions import ActionUseCases
from .use_cases.audit import AuditUseCases
from .use_cases.chat import ChatUseCase
from .use_cases.financial import FinancialUseCases
from .use_cases.profile import ProfileUseCases
from .use_cases.statements import StatementUseCases


@dataclass(frozen=True)
class ApplicationServices:
    financial: FinancialUseCases
    actions: ActionUseCases
    profiles: ProfileUseCases
    audit: AuditUseCases
    statements: StatementUseCases
    chat: ChatUseCase
    registry: ToolRegistry
    default_user: str
    mode: str  # "offline" or "live": shown in /health so the demo never runs in the wrong mode
    language_model: str
    decision_chain: tuple[str, ...]
