from neural_ledger.domain.shared.serialization import to_primitive

from .test_contracts import validate


def test_profile_data_and_questionnaire_match_their_contracts(services):
    profile = to_primitive(services.profiles.user_profile("camila"))
    questionnaire = to_primitive(services.profiles.questionnaire())
    for envelope in (profile, questionnaire):
        validate(envelope, "common/envelope.schema.json")
    validate(profile["data"], "outputs/user_profile.schema.json")
    validate(questionnaire["data"], "profile/questionnaire.schema.json")
