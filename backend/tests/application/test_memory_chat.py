"""ADR-048 §6 in the chat: memory-derived context is dropped once the memory it came from moves.

A turn that reads memory, and every later turn that saw it, is stamped with the consent generation and memory
revision. After a revocation, a reconsent, a confirmation or a deletion those entries never reach a model again; a turn
in flight is checked before each model call and before its reply is published or stored. The conversation itself
is kept: the user's own messages stay. A request already sent to a model cannot be taken back.
"""

from __future__ import annotations

import pytest

from neural_ledger.application.conversation import AssistantEntry, ToolResultEntry, UserEntry
from neural_ledger.application.services import narration
from tests.application.test_memory_writes import World
from tests.security.helpers import ScriptedFakeLLM, call, chat_with, say

SESSION = "s_mem_chat"
SALARY = 1_234_567


@pytest.fixture(params=["memory", "sqlite"])
def world(request, tmp_path) -> World:
    w = World(request.param, tmp_path)
    w.grant(w.ana)
    assert w.declare(w.ana, amount=SALARY, month="2026-09").ok
    return w


def _memory_entries(entries) -> list:
    return [e for e in entries if isinstance(e, (AssistantEntry, ToolResultEntry)) and (
        getattr(e, "name", None) == "get_user_memory" or any(c.name == "get_user_memory" for c in getattr(e, "tool_calls", ()))
        or (e.text if isinstance(e, AssistantEntry) else None) and "1,234,567" in (e.text or "")
    )]


class Hooked(ScriptedFakeLLM):
    """A model whose n-th answer first runs a side effect: the user revokes while the model is thinking."""

    def __init__(self, turns, hooks: dict) -> None:
        super().__init__(turns)
        self._hooks = hooks

    def respond(self, request):
        hook = self._hooks.pop(len(self.requests), None)
        if hook:
            hook()
        return super().respond(request)


def test_the_offline_flow_prepares_every_kind_of_card_and_passes_the_verifier(world):
    for message, status, candidates in (
        ("Desde noviembre gano 1.300.000", "READY", [1_300_000]),
        ("Antes ganaba 1.000.000 y ahora 1.300.000", "CHOOSE_AMOUNT", [1_000_000, 1_300_000]),
        ("Quiero que recuerdes mi sueldo", "ASK_AMOUNT", []),
    ):
        reply = world.services.chat.handle(SESSION, world.ana, message)
        card = reply.pending_memory_proposal
        assert (card["status"], card["candidates"]) == (status, candidates), reply.text
        assert reply.verification.ok and narration.SAVED_ONLY in reply.text and "nothing is saved" in reply.text
        assert reply.memory_dependency == {"consent_generation": 1, "memory_revision": 1}
    assert len(world.store.for_user(world.ana)) == 1  # three cards, still only the one declaration


def test_get_user_memory_narrates_the_declaration_and_says_it_is_saved_only(world):
    llm = ScriptedFakeLLM([call("get_user_memory"), say("")])  # the model is silent: the deterministic narration speaks
    reply = chat_with(world.services, world.adapters, llm).handle(SESSION, world.ana, "¿Qué sabes de mi sueldo?")
    assert "1,234,567 CLP" in reply.text and narration.SAVED_ONLY in reply.text and reply.verification.ok


def _three_turns(world: World, change) -> ScriptedFakeLLM:
    llm = ScriptedFakeLLM([call("get_user_memory"), say("You declared 1,234,567 CLP."), say("Noted."), say("ok")])
    chat = chat_with(world.services, world.adapters, llm)
    chat.handle(SESSION, world.ana, "¿Qué sabes de mi sueldo?")
    chat.handle(SESSION, world.ana, "Gracias, ¿y qué más?")  # saw the memory turn: derived from it as well
    assert _memory_entries(llm.requests[-1].entries)  # still valid here
    change()
    chat.handle(SESSION, world.ana, "Hola de nuevo")
    return llm


@pytest.mark.parametrize("change", ["revoke", "reconsent", "confirm", "delete"])
def test_stale_memory_context_never_reaches_a_model_again(world, change):
    def apply() -> None:
        if change in ("revoke", "reconsent"):
            world.memory.set_consent(world.ana, "s_1", {"consent": "revoked"})
            if change == "reconsent":
                world.grant(world.ana)
        elif change == "confirm":
            assert world.declare(world.ana, amount=1_300_000, month="2026-12", expected=1).ok
        else:
            (chain_id,) = {d.chain_id for d in world.store.for_user(world.ana)}
            assert world.memory.delete_chain(world.ana, "s_1", chain_id).ok

    llm = _three_turns(world, apply)
    last = llm.requests[-1].entries
    assert _memory_entries(last) == []
    assert not [e for e in last if isinstance(e, AssistantEntry) and e.text == "Noted."]  # the derived reply went too
    assert [e.text for e in last if isinstance(e, UserEntry)] == ["¿Qué sabes de mi sueldo?", "Gracias, ¿y qué más?", "Hola de nuevo"]


def test_a_turn_without_memory_is_never_stamped(world):
    llm = ScriptedFakeLLM([call("compute_protected_surplus"), say("ok"), say("ok")])
    chat = chat_with(world.services, world.adapters, llm)
    reply = chat.handle(SESSION, world.ana, "what is my surplus available?")
    assert reply.memory_dependency is None
    world.memory.set_consent(world.ana, "s_1", {"consent": "revoked"})
    chat.handle(SESSION, world.ana, "Hola")
    assert any(isinstance(e, ToolResultEntry) and e.name == "compute_protected_surplus" for e in llm.requests[-1].entries)


def test_a_revocation_while_the_model_answers_keeps_its_answer_from_being_published(world):
    revoke = lambda: world.memory.set_consent(world.ana, "s_1", {"consent": "revoked"})  # noqa: E731
    llm = Hooked([call("get_user_memory"), say("Your salary is 1,234,567 CLP and it is verified.")], {1: revoke})
    chat = chat_with(world.services, world.adapters, llm)
    reply = chat.handle(SESSION, world.ana, "¿Qué sabes de mi sueldo?")
    assert reply.text == narration.MEMORY_CHANGED and "1,234,567" not in reply.text
    assert reply.memory_dependency is None and reply.pending_memory_proposal is None and reply.facts == ()
    stored = chat._conversations.history(world.ana, SESSION)
    assert [type(e).__name__ for e in stored] == ["UserEntry", "AssistantEntry"] and stored[1].memory_stamp is None
    chat.handle(SESSION, world.ana, "¿y?")
    assert _memory_entries(llm.requests[-1].entries) == []


def test_a_revocation_between_tool_rounds_stops_the_next_model_call(world):
    revoke = lambda: world.memory.set_consent(world.ana, "s_1", {"consent": "revoked"})  # noqa: E731
    llm = ScriptedFakeLLM([call("get_user_memory"), say("You declared 1,234,567 CLP.")])
    real_invoke = world.services.registry.invoke

    def invoke_then_revoke(call_, ctx, **kwargs):
        outcome = real_invoke(call_, ctx, **kwargs)
        revoke()  # right after the tool read memory, before the model sees its result
        return outcome

    chat = chat_with(world.services, world.adapters, llm)
    chat._registry = type("R", (), {"invoke": staticmethod(invoke_then_revoke), "reads_memory": world.services.registry.reads_memory,
                                    "specs": world.services.registry.specs})()
    reply = chat.handle(SESSION, world.ana, "¿Qué sabes de mi sueldo?")
    assert len(llm.requests) == 1  # the memory result never went back to the model
    assert reply.text == narration.MEMORY_CHANGED


def test_a_card_from_before_a_revocation_is_marked_obsolete_by_its_counters(world):
    reply = world.services.chat.handle(SESSION, world.ana, "Desde noviembre gano 1.300.000")
    dependency = reply.memory_dependency
    world.memory.set_consent(world.ana, "s_1", {"consent": "revoked"})
    state = world.memory.consent(world.ana)
    assert (state.consent_generation, state.memory_revision) != (dependency["consent_generation"], dependency["memory_revision"])
    proposal_id = reply.pending_memory_proposal["proposal_id"]
    world.grant(world.ana)
    assert world.confirm(world.ana, proposal_id, expected=1).status == "PROPOSAL_STALE"
