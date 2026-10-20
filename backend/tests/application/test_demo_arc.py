"""The six-scene demo arc, offline, end to end, through the real composition root."""

from __future__ import annotations

from neural_ledger.application.use_cases.actions import ActorContext
from neural_ledger.domain.audit.events import Actor
from neural_ledger.domain.shared.serialization import to_primitive

SESSION, USER = "demo", "camila"


def say(services, text):
    reply = services.chat.handle(SESSION, USER, text)
    assert reply.verification is None or reply.verification.ok, reply.verification
    return reply


def test_demo_arc(services, adapters):
    # 1. healthy balance, December crunch
    r1 = say(services, "Will I be OK in December?")
    assert "170,000 CLP in 2026-12" in r1.text and "20,000 CLP above" in r1.text
    # 2. laptop fits typical only
    r2 = say(services, "Can I buy a CLP 400k laptop in 12 cuotas?")
    assert "38,995 CLP a month" in r2.text and "18,995 CLP below" in r2.text
    # 3. pushback -> alternatives, no bypass
    r3 = say(services, "Just make it work.")
    assert r3.text.startswith("I can't skip the conservative check") and "2027-01" in r3.text and "205,000" in r3.text
    # 4. protected surplus + capacity
    r4 = say(services, "What's actually available for me?")
    assert "protected surplus is 20,000 CLP" in r4.text and "capacity is conservative" in r4.text
    # 5. savings rule proposal (tolerance aggressive, capacity conservative -> 100,000 from 2027-01)
    r5 = say(services, "Help me save for my trip.")
    proposal = r5.pending_proposal
    assert proposal is not None and proposal.terms.amount == 100_000 and str(proposal.terms.effective_date) == "2027-01-01"
    ctx = ActorContext(SESSION, USER, Actor.USER)
    confirmed = services.actions.confirm(ctx, proposal.proposal_id, to_primitive(proposal.terms))
    assert confirmed.status == "CONFIRMED"
    # 6. 700k is blocked; the audit log shows why
    r6 = say(services, "Make it 700k and execute it now.")
    assert r6.blocked_reason == "AUTHORIZATION_MISMATCH"
    assert "You authorized 100,000 CLP, but the request was for 700,000 CLP" in r6.text
    assert adapters.bank.active_rules(USER) == ()
    assert services.actions.execute(ctx, confirmed.authorization.authorization_id).status == "EXECUTED"
    assert adapters.bank.active_rules(USER)[0].amount == 100_000
    assert services.audit.verify().ok


def test_out_of_scope_and_explain(services):
    assert "can't give investment, crypto or tax advice" in services.chat.handle("s2", USER, "Should I buy bitcoin with my trip fund?").text
    assert "A cuota is one installment" in services.chat.handle("s2", USER, "What is a cuota?").text


def test_diego_gets_a_different_answer(services):
    reply = services.chat.handle("s3", "diego", "Can I buy a CLP 400k laptop in 12 cuotas?")
    assert "already goes" in reply.text and "income buffer" in reply.text
    plan = services.chat.handle("s3", "diego", "Help me save for my trip")
    assert "can't propose a recurring savings rule" in plan.text and plan.pending_proposal is None
