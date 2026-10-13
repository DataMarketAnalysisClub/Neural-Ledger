"""One bounded repair for honest verifier rejections; dangerous claims are never retried."""

from __future__ import annotations

from neural_ledger.application.conversation import AssistantEntry, UserEntry
from tests.security.helpers import SESSION, USER, ScriptedFakeLLM, audit_kinds, call, chat_with, say

SURPLUS = "what is my surplus available?"
LAPTOP = "Can I buy a CLP 400k laptop in 12 cuotas?"
BAD_NUMBER = "Your protected surplus is 20,000 CLP and you could also spend 777,000 CLP."
GOOD = "Your protected surplus is 20,000 CLP."


def texts(entries) -> list[str]:
    return [e.text for e in entries if isinstance(e, (UserEntry, AssistantEntry)) and e.text]


def test_an_unsupported_number_is_repaired_once(services, adapters):
    llm = ScriptedFakeLLM([call("compute_protected_surplus"), say(BAD_NUMBER), say(GOOD)])
    reply = chat_with(services, adapters, llm).handle(SESSION, USER, SURPLUS)
    assert reply.text == GOOD and not reply.fallback_used and reply.verification.ok
    assert audit_kinds(adapters).count("VERIFICATION_FAILED") == 1
    note = llm.requests[-1].entries[-1]
    assert isinstance(note, UserEntry) and "777,000" in note.text and "rejected by the verifier" in note.text


def test_the_rejected_reply_and_the_note_never_reach_the_stored_history(services, adapters):
    llm = ScriptedFakeLLM([call("compute_protected_surplus"), say(BAD_NUMBER), say(GOOD), say("ok")])
    chat = chat_with(services, adapters, llm)
    chat.handle(SESSION, USER, SURPLUS)
    chat.handle(SESSION, USER, "thanks")
    remembered = texts(llm.requests[-1].entries)
    assert GOOD in remembered
    assert not any("777,000" in t or "rejected by the verifier" in t for t in remembered)


def test_a_missing_warning_is_repaired_once(services, adapters):
    llm = ScriptedFakeLLM([
        call("simulate_purchase", amount=400_000, installments=12),
        say("It fits a typical month but not the conservative one."),
        say("It fits a typical month but not the conservative one. I assumed a 2.5% monthly rate and that the first cuota is billed in 2026-12."),
    ])
    reply = chat_with(services, adapters, llm).handle(SESSION, USER, LAPTOP)
    assert not reply.fallback_used and "assumed" in reply.text
    note = llm.requests[-1].entries[-1]
    assert isinstance(note, UserEntry) and "was not mentioned" in note.text and "FIRST_INSTALLMENT_ASSUMED" in note.text


def test_a_second_rejection_falls_back_to_the_deterministic_narration(services, adapters):
    llm = ScriptedFakeLLM([call("compute_protected_surplus"), say(BAD_NUMBER), say(BAD_NUMBER)])
    reply = chat_with(services, adapters, llm).handle(SESSION, USER, SURPLUS)
    assert reply.fallback_used and "777,000" not in reply.text and "20,000 CLP" in reply.text and reply.verification.ok
    assert audit_kinds(adapters).count("VERIFICATION_FAILED") == 2


def test_dangerous_claims_are_not_retried(services, adapters):
    llm = ScriptedFakeLLM([call("compute_protected_surplus"), say("It is safe money: you can spend 777,000 CLP."), say(GOOD)])
    reply = chat_with(services, adapters, llm).handle(SESSION, USER, SURPLUS)
    assert reply.fallback_used and "safe money" not in reply.text
    assert len(llm.requests) == 2  # the tool round and the rejected reply; no repair round
    assert audit_kinds(adapters).count("VERIFICATION_FAILED") == 1


def test_a_failed_execution_is_not_retried(services, adapters):
    from tests.security.helpers import confirmed_authorization

    auth = confirmed_authorization(services)
    adapters.bank.fail_next = True
    llm = ScriptedFakeLLM([call("execute_sandbox_action", authorization_id=auth.authorization_id), say("Done. Total 777,000 CLP."), say("ok")])
    reply = chat_with(services, adapters, llm).handle(SESSION, USER, "execute the savings rule")
    assert reply.fallback_used and "could not complete" in reply.text
    assert len(llm.requests) == 2
