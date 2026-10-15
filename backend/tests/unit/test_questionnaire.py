import pytest

from neural_ledger.domain.finance.profile import RiskProfile
from neural_ledger.domain.shared.errors import InvalidInput
from neural_ledger.domain.user.profile import QuestionnaireAnswer
from neural_ledger.domain.user.questionnaire import CURRENT_VERSION, REGISTRY, derive_tolerance, validate_submission


def test_registry_matches_option_order_and_copy_keys():
    definition = REGISTRY[CURRENT_VERSION]
    assert [question.question_id for question in definition.questions] == [
        "set_aside", "tight_month", "goal_vs_room", "surprise", "habit"
    ]
    for question in definition.questions:
        assert question.copy_key == f"questionnaire.{question.question_id}.prompt"
        assert [option.score for option in question.options] == [0, 1, 2]
        for option in question.options:
            assert option.copy_key == f"questionnaire.{question.question_id}.options.{option.option_id}"


def test_submitted_example_derives_moderate():
    answers = tuple(QuestionnaireAnswer(q.question_id, q.options[1].option_id) for q in REGISTRY[CURRENT_VERSION].questions)
    assert derive_tolerance(CURRENT_VERSION, validate_submission(CURRENT_VERSION, answers)) is RiskProfile.MODERATE


@pytest.mark.parametrize("change", [
    lambda a: a[:-1],
    lambda a: (*a[:-1], a[0]),
    lambda a: (QuestionnaireAnswer("unknown", "small_part"), *a[1:]),
    lambda a: (QuestionnaireAnswer("set_aside", "unknown"), *a[1:]),
])
def test_submission_rejects_incomplete_duplicate_and_unknown_answers(change):
    answers = tuple(QuestionnaireAnswer(q.question_id, q.options[0].option_id) for q in REGISTRY[CURRENT_VERSION].questions)
    with pytest.raises(InvalidInput) as error:
        validate_submission(CURRENT_VERSION, change(answers))
    assert error.value.field == "answers"


def test_submission_rejects_non_current_version():
    with pytest.raises(InvalidInput) as error:
        validate_submission("pq-0.0", ())
    assert error.value.field == "version"
