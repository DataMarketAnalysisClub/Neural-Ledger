from neural_ledger.adapters.outbound.persistence.memory import InMemoryConversationStore
from neural_ledger.application.conversation import UserEntry
from tests.security.helpers import ScriptedFakeLLM


def test_history_is_scoped_by_user_when_session_is_shared():
    store = InMemoryConversationStore()
    store.append("camila", "shared", (UserEntry("private Camila text"),), 20)
    assert store.history("usr_one", "shared") == ()
    assert store.history("camila", "shared") == (UserEntry("private Camila text"),)


def test_chat_and_tolerance_do_not_read_other_users_history(services):
    model = ScriptedFakeLLM(())
    services.chat._llm = model
    services.chat.handle("shared", "camila", "Please help me save for my trip")
    result = services.profiles.risk_tolerance("usr_one", "shared")
    services.chat.handle("shared", "usr_one", "Please help me save for my trip")

    assert model.requests[1].entries == (UserEntry("Please help me save for my trip"),)
    assert result.data.language_signal is None
