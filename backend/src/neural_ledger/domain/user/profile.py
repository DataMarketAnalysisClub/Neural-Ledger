"""The typed user record (replaces the 'complete access User Record' and the graph memory).

The agent can READ it (T0). Changes are proposals the user confirms; free-text instructions
are never stored here, so the record cannot become a prompt-injection channel.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from ..finance.profile import RiskProfile
from ..shared.errors import InvalidInput
from .questionnaire import REGISTRY, validate_answers


def validate_display_name(name: str) -> str:
    if not 1 <= len(name) <= 40 or any(ch not in " .'-" and not unicodedata.category(ch).startswith("L") for ch in name):
        raise InvalidInput("display_name", "use 1-40 Unicode letters, spaces, periods, apostrophes or hyphens")
    return name


@dataclass(frozen=True, slots=True)
class QuestionnaireAnswer:
    question_id: str
    option_id: str


@dataclass(frozen=True, slots=True)
class UserProfile:
    user_id: str
    display_name: str
    language: str = "en"
    declared_tolerance: RiskProfile | None = None
    questionnaire: tuple[QuestionnaireAnswer, ...] = ()
    questionnaire_version: str | None = None

    def __post_init__(self) -> None:
        validate_display_name(self.display_name)
        if len(self.language) != 2 or not self.language.isascii() or not self.language.islower() or not self.language.isalpha():
            raise InvalidInput("language", "use two lowercase ASCII letters")
        if self.questionnaire_version is None:
            if self.questionnaire:
                raise InvalidInput("questionnaire_version", "answers require a questionnaire version")
        elif self.questionnaire_version not in REGISTRY:
            raise InvalidInput("questionnaire_version", "unknown questionnaire version", tuple(REGISTRY))
        else:
            validate_answers(self.questionnaire_version, self.questionnaire)
