from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from ..finance.profile import RiskProfile
from ..shared.errors import InvalidInput

if TYPE_CHECKING:
    from .profile import QuestionnaireAnswer


@dataclass(frozen=True, slots=True)
class Option:
    option_id: str
    copy_key: str
    score: int


@dataclass(frozen=True, slots=True)
class Question:
    question_id: str
    copy_key: str
    options: tuple[Option, ...]


@dataclass(frozen=True, slots=True)
class QuestionnaireDefinition:
    version: str
    questions: tuple[Question, ...]


CURRENT_VERSION: Final = "pq-0.1"
_OPTIONS: Final = (
    ("set_aside", ("small_part", "about_half", "most")),
    ("tight_month", ("pause", "keep_cut_elsewhere", "keep_as_intended")),
    ("goal_vs_room", ("spending_room", "balance", "goal_on_time")),
    ("surprise", ("very_stressed", "uneasy_but_ok", "calm")),
    ("habit", ("never_or_stopped", "sometimes", "regularly")),
)
REGISTRY: Final[Mapping[str, QuestionnaireDefinition]] = MappingProxyType({
    CURRENT_VERSION: QuestionnaireDefinition(
        CURRENT_VERSION,
        tuple(
            Question(
                question_id,
                f"questionnaire.{question_id}.prompt",
                tuple(Option(option_id, f"questionnaire.{question_id}.options.{option_id}", score) for score, option_id in enumerate(option_ids)),
            )
            for question_id, option_ids in _OPTIONS
        ),
    )
})


def validate_answers(version: str, answers: Sequence[QuestionnaireAnswer]) -> tuple[QuestionnaireAnswer, ...]:
    definition = REGISTRY.get(version)
    if definition is None:
        raise InvalidInput("version", "unknown questionnaire version", tuple(REGISTRY))
    by_question = {question.question_id: question for question in definition.questions}
    if len(answers) != len(by_question) or len({answer.question_id for answer in answers}) != len(by_question):
        raise InvalidInput("answers", "answer every question exactly once")
    for answer in answers:
        question = by_question.get(answer.question_id)
        if question is None or answer.option_id not in {option.option_id for option in question.options}:
            raise InvalidInput("answers", "unknown question or option")
    return tuple(answers)


def validate_submission(version: str, answers: Sequence[QuestionnaireAnswer]) -> tuple[QuestionnaireAnswer, ...]:
    if version != CURRENT_VERSION:
        raise InvalidInput("version", "only the current questionnaire can be submitted", (CURRENT_VERSION,))
    return validate_answers(version, answers)


def derive_tolerance(version: str, answers: Sequence[QuestionnaireAnswer]) -> RiskProfile:
    valid = validate_answers(version, answers)
    definition = REGISTRY[version]
    selected = {answer.question_id: answer.option_id for answer in valid}
    scores = {
        question.question_id: next(option.score for option in question.options if option.option_id == selected[question.question_id])
        for question in definition.questions
    }
    total = sum(scores.values())
    if total <= 3:
        return RiskProfile.CONSERVATIVE
    if total <= 7 or scores["tight_month"] == 0:
        return RiskProfile.MODERATE
    return RiskProfile.AGGRESSIVE
