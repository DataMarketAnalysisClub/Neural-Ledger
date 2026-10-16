from neural_ledger.application.services.narration import narrate
from neural_ledger.domain.agent.verification import verify_explanation
from neural_ledger.domain.shared.serialization import to_primitive


def test_wrapped_profile_narrates_name_without_serializing_wrapper(services):
    envelope = to_primitive(services.profiles.user_profile("camila"))
    assert envelope["data"]["display_name"] == {"untrusted_text": "Camila"}
    reply = narrate((("get_user_profile", envelope),), "CLP")
    assert reply == "Profile loaded for Camila."
    assert verify_explanation(reply, (), ()).ok
