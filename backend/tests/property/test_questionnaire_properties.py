from itertools import product

import pytest

from neural_ledger.domain.finance.profile import RiskProfile
from neural_ledger.domain.user.profile import QuestionnaireAnswer
from neural_ledger.domain.user.questionnaire import CURRENT_VERSION, REGISTRY, derive_tolerance


@pytest.mark.property
def test_every_complete_answer_combination_is_total_deterministic_and_monotone():
    questions = REGISTRY[CURRENT_VERSION].questions
    for scores in product(range(3), repeat=5):
        answers = tuple(QuestionnaireAnswer(question.question_id, question.options[score].option_id) for question, score in zip(questions, scores))
        actual = derive_tolerance(CURRENT_VERSION, answers)
        expected = RiskProfile.CONSERVATIVE if sum(scores) <= 3 else RiskProfile.MODERATE if sum(scores) <= 7 or scores[1] == 0 else RiskProfile.AGGRESSIVE
        assert actual is expected
        assert derive_tolerance(CURRENT_VERSION, answers) is actual
        for index, score in enumerate(scores):
            if score < 2:
                raised = tuple(QuestionnaireAnswer(question.question_id, question.options[score + (position == index)].option_id) for position, (question, score) in enumerate(zip(questions, scores)))
                assert derive_tolerance(CURRENT_VERSION, raised).rank >= actual.rank
