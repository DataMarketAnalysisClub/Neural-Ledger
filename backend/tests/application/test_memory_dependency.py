"""ADR-048 §6: what derives from memory, and the two points where a chat turn is ordered against memory changes.

Dependency propagates: once a model request has seen memory, every call it asks for and every result, fact, card and
word built on them depends on memory, even a secondary tool that never reads memory itself (a model can pass the
salary it read as a purchase amount). When memory moves, none of that is published or kept. Calls asked for before
memory entered the turn are independent and keep working.

The dispatch and publication boundaries run inside the user's MemoryFence, which every memory change also takes; it is
never held through a model call, never blocks another user, and derived reads are validated against the counters.
Synthetic data, both persistence adapters, deterministic hooks (threads only with events and timeouts).
"""

from __future__ import annotations

import threading
from datetime import date

import pytest

from neural_ledger.adapters.outbound.statements.synthetic import SyntheticStatements
from neural_ledger.application.conversation import ModelTurn, ToolCall, UserEntry
from neural_ledger.application.services import narration
from tests.application.test_memory_writes import World
from tests.security.helpers import ScriptedFakeLLM, call, chat_with, say

SESSION = "s_mem_dep"
SALARY = 1_234_567
SHOWN = "1,234,567"  # how narration writes it
WAIT = 5  # seconds: a thread that has not finished by then is blocked, and the test fails instead of hanging


@pytest.fixture(params=["memory", "sqlite"])
def world(request, tmp_path) -> World:
    w = World(request.param, tmp_path)
    w.grant(w.ana)
    assert w.declare(w.ana, amount=SALARY, month="2026-09").ok
    for f in SyntheticStatements().checking(21, date(2026, 9, 30), 8, None, 1_100_000):  # a financial model for Ana
        assert w.services.statements.import_statement(w.ana, f.content).ok
    return w


def _change(world: World, kind: str) -> None:
    if kind == "revoke":
        assert world.memory.set_consent(world.ana, "s_1", {"consent": "revoked"}).ok
    elif kind == "confirm":
        assert world.declare(world.ana, amount=1_300_000, month="2026-12", expected=1).ok
    else:
        (chain_id,) = {d.chain_id for d in world.store.for_user(world.ana)}
        assert world.memory.delete_chain(world.ana, "s_1", chain_id).ok


def _after_invoking(chat, world: World, name: str, side_effect) -> None:
    """Run side_effect right after the tool `name` returns, before the model sees its result."""
    real = world.services.registry.invoke

    def invoke(call_, ctx, **kwargs):
        outcome = real(call_, ctx, **kwargs)
        if call_.name == name:
            side_effect()
        return outcome

    chat._registry = type("R", (), {
        "invoke": staticmethod(invoke), "reads_memory": world.services.registry.reads_memory, "specs": world.services.registry.specs,
    })()


def _leaks(reply, amount: int = SALARY) -> list:
    """Every place of a reply where the amount could survive."""
    found = [f for f in reply.facts if f.value == amount]
    if SHOWN in reply.text or str(amount) in reply.text:
        found.append(reply.text)
    for card in (reply.pending_proposal, reply.pending_memory_proposal, reply.pending_expense, *reply.actions):
        if card is not None and str(amount) in repr(card):
            found.append(card)
    return found


# ---- A: a secondary tool fed with a memory-derived amount -----------------------------------------------------

@pytest.mark.parametrize("kind", ["revoke", "confirm", "delete"])
def test_a_secondary_result_built_on_memory_is_dropped_when_memory_moves(world, kind):
    llm = ScriptedFakeLLM([
        call("get_user_memory"),
        call("simulate_purchase", amount=SALARY, installments=1),  # the model reuses the salary it read
        say("Hola."),  # never reached by the first turn: it stops at the dispatch boundary after the change
    ])
    chat = chat_with(world.services, world.adapters, llm)
    _after_invoking(chat, world, "simulate_purchase", lambda: _change(world, kind))

    reply = chat.handle(SESSION, world.ana, "¿Puedo comprar una tele del valor de mi sueldo?")

    assert reply.text == narration.MEMORY_CHANGED and _leaks(reply) == []
    assert reply.tools_called == () and reply.memory_dependency is None and reply.pending_proposal is None
    stored = chat._conversations.history(world.ana, SESSION)
    assert [type(e).__name__ for e in stored] == ["UserEntry", "AssistantEntry"]
    assert stored[1].text == narration.MEMORY_CHANGED and stored[1].memory_stamp is None  # not relabelled as ordinary history
    assert len(llm.requests) == 2
    chat.handle(SESSION, world.ana, "Hola")
    later = repr(llm.requests[2].entries)  # what the next turn hands the model: history and the new message
    assert str(SALARY) not in later and SHOWN not in later


def test_without_a_change_the_same_turn_is_published_and_stamped(world):
    """The positive control: the secondary result is real, and it is published when memory holds."""
    llm = ScriptedFakeLLM([call("get_user_memory"), call("simulate_purchase", amount=SALARY, installments=1), say("")])
    chat = chat_with(world.services, world.adapters, llm)
    reply = chat.handle(SESSION, world.ana, "¿Puedo comprar una tele del valor de mi sueldo?")
    assert any(f.key == "purchase.amount" and f.value == SALARY for f in reply.facts)
    assert reply.memory_dependency == {"consent_generation": 1, "memory_revision": 1}
    assert all(e.memory_stamp == (1, 1) for e in chat._conversations.history(world.ana, SESSION) if not isinstance(e, UserEntry))


def test_a_dependent_stateful_call_is_not_executed_once_memory_moved(world):
    message = f"Mi piso de liquidez es {SALARY}"
    floor = call("propose_liquidity_floor", amount=SALARY)

    def proposals() -> list:
        return [p for p in world.adapters.actions_repo.for_session(SESSION)[0] if p.user_id == world.ana]

    control = chat_with(world.services, world.adapters, ScriptedFakeLLM([call("get_user_memory"), floor, say("")]))
    assert control.handle("s_control", world.ana, message).pending_proposal is not None  # it would have been created

    class RevokingModel(ScriptedFakeLLM):  # the user revokes while the model is choosing the dependent call
        def respond(self, request):
            turn = super().respond(request)
            if len(self.requests) == 2:
                _change(world, "revoke")
            return turn

    chat = chat_with(world.services, world.adapters, RevokingModel([call("get_user_memory"), floor, say("Done.")]))
    reply = chat.handle(SESSION, world.ana, message)
    assert proposals() == []  # never executed, so nothing to roll back
    assert reply.pending_proposal is None and reply.actions == () and reply.text == narration.MEMORY_CHANGED


def test_calls_asked_for_before_memory_entered_the_turn_stay_independent(world):
    both = ModelTurn(None, (ToolCall("c_surplus", "compute_protected_surplus", {}), ToolCall("c_mem", "get_user_memory", {})), "fake")
    llm = ScriptedFakeLLM([both, say(f"You declared {SHOWN} CLP.")])
    chat = chat_with(world.services, world.adapters, llm)
    _after_invoking(chat, world, "get_user_memory", lambda: _change(world, "revoke"))

    reply = chat.handle(SESSION, world.ana, "what is my surplus available?")

    assert reply.tools_called == ("compute_protected_surplus",) and reply.facts and _leaks(reply) == []
    assert reply.text.endswith(narration.MEMORY_CHANGED) and reply.text != narration.MEMORY_CHANGED  # the surplus is said
    assert reply.verification.ok


# ---- B: the dispatch and publication boundaries -----------------------------------------------------------------

def test_a_revocation_just_before_the_dispatch_boundary_keeps_the_request_from_being_sent(world):
    llm = ScriptedFakeLLM([call("get_user_memory"), say(f"You declared {SHOWN} CLP.")])
    chat = chat_with(world.services, world.adapters, llm)
    real = world.memory.authorized

    def revoke_then_authorize(user_id, stamp):
        _change(world, "revoke")  # lands right before the check, ordered before it by the fence
        return real(user_id, stamp)

    world.memory.authorized = revoke_then_authorize
    reply = chat.handle(SESSION, world.ana, "¿Qué sabes de mi sueldo?")
    assert len(llm.requests) == 1  # the memory result never went to a model
    assert reply.text == narration.MEMORY_CHANGED and _leaks(reply) == []


def test_a_revocation_while_the_reply_is_built_keeps_it_from_being_published(world, monkeypatch):
    """After the last model answer, during narration: the gap between the old final check and the history write."""
    llm = ScriptedFakeLLM([call("get_user_memory"), say("")])  # a silent model: the deterministic narration speaks
    chat = chat_with(world.services, world.adapters, llm)
    real = narration.narrate
    calls = []

    def narrate_then_revoke(results, currency):
        text = real(results, currency)
        if not calls:
            calls.append(1)
            _change(world, "revoke")
        return text

    monkeypatch.setattr(narration, "narrate", narrate_then_revoke)
    reply = chat.handle(SESSION, world.ana, "¿Qué sabes de mi sueldo?")
    assert calls and reply.text == narration.MEMORY_CHANGED and _leaks(reply) == [] and reply.memory_dependency is None
    stored = chat._conversations.history(world.ana, SESSION)
    assert [type(e).__name__ for e in stored] == ["UserEntry", "AssistantEntry"] and stored[1].memory_stamp is None
    assert SHOWN not in repr(stored)


def test_publication_and_a_memory_change_never_interleave(world):
    """Inside the fence the check and the history write are one step: a revocation waits for it, then lands."""
    stamp = world.memory.stamp(world.ana)
    writing, release, revoked = threading.Event(), threading.Event(), threading.Event()

    def publish() -> None:
        writing.set()
        assert release.wait(WAIT)

    def revoke() -> None:
        _change(world, "revoke")
        revoked.set()

    publisher = threading.Thread(target=lambda: world.memory.publish_if_current(world.ana, stamp, publish))
    publisher.start()
    assert writing.wait(WAIT)
    other = threading.Thread(target=revoke)
    other.start()
    assert not revoked.wait(0.2)  # held off while the publication writes
    release.set()
    publisher.join(WAIT)
    other.join(WAIT)
    assert revoked.is_set() and world.memory.stamp(world.ana) != stamp
    assert world.memory.publish_if_current(world.ana, stamp, lambda: pytest.fail("published under a stale stamp")) is False


def test_a_revocation_during_an_in_flight_model_call_is_never_blocked(world):
    done = threading.Event()

    class SlowModel(ScriptedFakeLLM):  # the model is still answering while the user revokes from another request
        def respond(self, request):
            if len(self.requests) == 1:
                worker = threading.Thread(target=lambda: (_change(world, "revoke"), done.set()))
                worker.start()
                assert done.wait(WAIT), "the revocation waited for the model call"
            return super().respond(request)

    chat = chat_with(world.services, world.adapters, SlowModel([call("get_user_memory"), say(f"You declared {SHOWN} CLP.")]))
    reply = chat.handle(SESSION, world.ana, "¿Qué sabes de mi sueldo?")
    assert reply.text == narration.MEMORY_CHANGED  # the request was already sent; its answer is not published


def test_a_held_fence_never_blocks_another_user(world):
    world.grant(world.bea)
    held, release, other_done = threading.Event(), threading.Event(), threading.Event()

    def hold() -> None:
        with world.memory._fence.held(world.ana):
            held.set()
            release.wait(WAIT)

    holder = threading.Thread(target=hold)
    holder.start()
    assert held.wait(WAIT)
    threading.Thread(target=lambda: (world.memory.set_consent(world.bea, "s_1", {"consent": "revoked"}), other_done.set())).start()
    assert other_done.wait(WAIT)
    release.set()
    holder.join(WAIT)


def test_a_memory_independent_turn_never_touches_the_fence(world):
    def fail(*_args):
        raise AssertionError("an independent turn went through a memory boundary")

    world.memory.authorized = fail
    world.memory.publish_if_current = fail
    llm = ScriptedFakeLLM([call("compute_protected_surplus"), say("")])
    reply = chat_with(world.services, world.adapters, llm).handle(SESSION, world.ana, "what is my surplus available?")
    assert reply.memory_dependency is None and reply.facts and reply.verification.ok


# ---- B: derived reads see one consistent consent, declarations and evidence -------------------------------------

def _on_evidence_read(world: World, side_effect) -> list:
    """Run side_effect on every read of Ana's statements: between the consent and the evidence a derived read uses."""
    store = world.services.memory._statements
    real = store.for_user
    reads = []

    def for_user(user_id):
        if user_id == world.ana:
            reads.append(1)
            side_effect(len(reads))
        return real(user_id)

    store.for_user = for_user
    return reads


def test_a_revocation_between_the_consent_and_the_evidence_reads_derives_nothing(world):
    _on_evidence_read(world, lambda n: n == 1 and _change(world, "revoke"))
    view = world.memory.view(world.ana)
    assert view["consent"] == "revoked" and [item["check"] for item in view["items"]] == [None]

    world.grant(world.ana)
    _on_evidence_read(world, lambda n: n == 1 and _change(world, "revoke"))
    summary, state = world.memory.summary(world.ana)
    assert summary["consent"] == "revoked" and summary["items"] == [] and state.consent.value == "revoked"


def test_counters_that_keep_moving_end_in_a_read_that_derives_nothing(world):
    def confirm_another(n: int) -> None:  # consent stays granted; every evidence read sees a new revision land
        assert world.declare(world.ana, amount=SALARY + n, month="2026-09", expected=n).ok

    reads = _on_evidence_read(world, confirm_another)
    view = world.memory.view(world.ana)
    assert len(reads) == 3  # READ_ATTEMPTS, then the fallback, which reads no evidence
    assert view["consent"] == "granted" and [item["check"] for item in view["items"]] == [None]
    assert view["items"][0]["versions"] == 4  # the declarations themselves are still the user's to see
