"""The typed user record (replaces the 'complete access User Record' and the graph memory).

The agent can READ it (T0). Changes are proposals the user confirms; free-text instructions
are never stored here, so the record cannot become a prompt-injection channel.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..finance.profile import RiskProfile


@dataclass(frozen=True, slots=True)
class QuestionnaireAnswer:
    question_id: str
    answer: str


@dataclass(frozen=True, slots=True)
class UserProfile:
    user_id: str
    display_name: str
    language: str = "en"
    declared_tolerance: RiskProfile | None = None
    questionnaire: tuple[QuestionnaireAnswer, ...] = ()
