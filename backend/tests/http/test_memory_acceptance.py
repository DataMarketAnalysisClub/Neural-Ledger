"""ADR-048 saved-only release: the replacement acceptance matrix, end to end over HTTP, offline, on both adapters.

The original plan's eleven scenarios (§17) could not be recovered: neither the repository nor the 2026-10-19
handoff lists them. These eleven replace them, pending approval:

A1 no consent: no card, 428 on writes, the view lists without a check, the tool is empty
A2 consent, one amount in chat (READY), confirm: one version with the chat origin, audited, saved only
A3 two amounts (CHOOSE_AMOUNT): the user picks; nothing picks for them
A4 no amount (ASK_AMOUNT): the user types it
A5 a raise with no chain: base and change saved together
A6 Perfil edit as a new version; a stale expected_version is VERSION_CONFLICT
A7 expiry exactly at the TTL is PROPOSAL_STALE; a replay is PROPOSAL_USED
A8 revocation keeps declarations, drops memory-derived chat context; reconsent revives no card
A9 an import that changes the evidence is audited once; an identical re-import is not
A10 export lists every version; deleting the chain removes all and kills pending cards; the revision keeps counting
A11 account deletion with a pending card removes every memory record; the other account is untouched
A12 (every scenario) no financial number moves: an account with its own statements reads the same before and after

Added by the review rework, not recovered scenarios either, and with the same status (pending approval); each lives
next to the code it fences:
A13 a secondary tool fed a memory amount: its result, facts, card and words are dropped when memory moves mid-turn,
    and stay out of later model context (tests/application/test_memory_dependency.py)
A14 the dispatch and publication boundaries and validated derived reads, revocation during a model call never
    blocked, other users never blocked (same file)
A15 an import that started before its account was deleted recreates nothing, at any step or retry
    (tests/security/test_import_after_deletion.py); the account export carries memory (tests/security/test_data_export.py)
A16 the web hides a whole reply whose memory moved, also one that arrives late or out of order
    (web/src/features/copilot/CopilotPage.test.tsx, web/src/features/memory/counters.test.ts, web/src/api/hooks.test.tsx)
"""

from __future__ import annotations

from datetime import date

import pytest

from neural_ledger.adapters.outbound.statements.synthetic import SyntheticStatements
from tests.http.test_memory_api import AMOUNT, PASSWORD, SALARY, Api
from tests.statement_samples import santander_xlsx


@pytest.fixture(params=["memory", "sqlite"])
def api(request, tmp_path) -> Api:
    return Api(request.param, tmp_path)


def _chat(client, message: str, session: str = "s_acc") -> dict:
    return client.post("/v1/chat", json={"session_id": session, "message": message}).json()


def _confirm(client, card: dict, **body):
    payload = {"salary_net": SALARY, "expected_version": card["expected_version"], **body}
    return client.post(f"/v1/memory/proposals/{card['proposal_id']}/confirm", json=payload)


def _kinds(client) -> list[str]:
    return [e["kind"] for e in client.get("/v1/audit").json()["events"]]


def test_a1_without_consent_nothing_is_prepared_or_written(api):
    client, _ = api.signup("a1@accounts.invalid")
    reply = _chat(client, "Mi sueldo líquido es 1.234.567")
    assert reply["pending_memory_proposal"] is None and "permission" in reply["text"]
    assert client.put("/v1/profile/income", json={"salary_net": SALARY, "expected_version": 0}).status_code == 428
    assert client.get("/v1/memory").json() == {"catalog_version": "mem-0.1", "consent": "missing", "items": []}
    assert api.services.memory.summary(api.services.accounts.resolve(client.cookies["nl_session"]).user_id)[0]["items"] == []


def test_a2_a_single_amount_is_confirmed_once_with_the_servers_origin(api):
    client, _ = api.signup("a2@accounts.invalid")
    client.put("/v1/memory/consent", json={"consent": "granted"})
    card = _chat(client, "Desde noviembre gano 1.234.567")["pending_memory_proposal"]
    assert card["status"] == "READY" and card["candidates"] == [AMOUNT]
    (item,) = _confirm(client, card, session_id="forged").json()["items"]
    declared = item["upcoming"] or item["current"]
    assert declared["origin"]["kind"] == "chat" and declared["origin"]["session_id"] == "s_acc"
    assert item["check"]["numeric_effect"] == "saved_only" and "MEMORY_CONFIRMED" in _kinds(client)


def test_a3_two_amounts_are_the_users_choice(api):
    client, _ = api.signup("a3@accounts.invalid")
    client.put("/v1/memory/consent", json={"consent": "granted"})
    card = _chat(client, "Antes ganaba 1.000.000 y ahora 1.300.000")["pending_memory_proposal"]
    assert card["status"] == "CHOOSE_AMOUNT" and card["candidates"] == [1_000_000, 1_300_000]
    assert client.get("/v1/memory").json()["items"] == []
    view = _confirm(client, card, salary_net={**SALARY, "amount": 1_300_000}).json()
    assert (view["items"][0]["upcoming"] or view["items"][0]["current"])["value"]["salary_net"]["amount"] == 1_300_000


def test_a4_no_amount_is_typed_by_the_user(api):
    client, _ = api.signup("a4@accounts.invalid")
    client.put("/v1/memory/consent", json={"consent": "granted"})
    card = _chat(client, "Quiero que recuerdes mi sueldo")["pending_memory_proposal"]
    assert card["status"] == "ASK_AMOUNT" and card["candidates"] == []
    assert _confirm(client, card, salary_net={**SALARY, "amount": 987_654}).status_code == 200


def test_a5_a_raise_saves_its_base_with_it(api):
    client, _ = api.signup("a5@accounts.invalid")
    client.put("/v1/memory/consent", json={"consent": "granted"})
    card = _chat(client, "Me subieron el sueldo a 1.234.567 desde noviembre")["pending_memory_proposal"]
    assert card["needs_base"] is True
    view = _confirm(client, card, base={"amount": 1_000_000, "net": True, "effective_from": "2026-06"}).json()
    assert view["items"][0]["versions"] == 2
    assert [d["version"] for d in client.get("/v1/memory/export").json()["declarations"]] == [1, 2]


def test_a6_perfil_edits_append_and_a_stale_edit_conflicts(api):
    client, _ = api.signup("a6@accounts.invalid")
    client.put("/v1/memory/consent", json={"consent": "granted"})
    assert client.put("/v1/profile/income", json={"salary_net": SALARY, "expected_version": 0}).status_code == 200
    assert client.put("/v1/profile/income", json={"salary_net": {**SALARY, "amount": 1_300_000}, "expected_version": 1}).status_code == 200
    stale = client.put("/v1/profile/income", json={"salary_net": SALARY, "expected_version": 1})
    assert stale.status_code == 409 and stale.json()["status"] == "VERSION_CONFLICT"


def test_a7_expiry_at_the_ttl_and_a_replay(api):
    client, _ = api.signup("a7@accounts.invalid")
    client.put("/v1/memory/consent", json={"consent": "granted"})
    used = _chat(client, "Mi sueldo líquido es 1.234.567")["pending_memory_proposal"]
    assert _confirm(client, used).status_code == 200
    assert _confirm(client, used).json()["status"] == "PROPOSAL_USED"
    late = _chat(client, "Ahora gano 1.300.000")["pending_memory_proposal"]
    api.adapters.clock.advance(minutes=30)
    assert _confirm(client, late).json()["status"] == "PROPOSAL_STALE"


def test_a8_revocation_keeps_declarations_and_reconsent_revives_nothing(api):
    client, _ = api.signup("a8@accounts.invalid")
    client.put("/v1/memory/consent", json={"consent": "granted"})
    assert client.put("/v1/profile/income", json={"salary_net": SALARY, "expected_version": 0}).status_code == 200
    reply = _chat(client, "Me subieron el sueldo a 1.300.000")
    card, dependency = reply["pending_memory_proposal"], reply["memory_dependency"]
    client.put("/v1/memory/consent", json={"consent": "revoked"})
    assert len(client.get("/v1/memory/export").json()["declarations"]) == 1
    assert client.get("/v1/memory/consent").json()["consent_generation"] != dependency["consent_generation"]  # the card is obsolete
    client.put("/v1/memory/consent", json={"consent": "granted"})
    assert _confirm(client, card).json()["status"] == "PROPOSAL_STALE"


def test_a9_an_import_audits_its_evidence_change_once(api):
    client, _ = api.signup("a9@accounts.invalid")
    client.put("/v1/memory/consent", json={"consent": "granted"})
    client.put("/v1/profile/income", json={"salary_net": {"amount": 1_200_000, "net": True, "effective_from": "2026-09"}, "expected_version": 0})
    september = santander_xlsx(movements=(("30/09", "O.Gerencia", "0000000009 REMUNERACION EMPRESA", "", 1_200_000),))
    october = santander_xlsx(movements=(("02/10", "Sucursal Uno", "Compra Nacional VD CAFE TWO", "2442020", -8_969),), period=("01/10/2026", "31/10/2026"))
    for content in (september, october, october, september):
        assert client.post("/v1/statements", content=content).json()["status"] == "OK"
    assert _kinds(client).count("MEMORY_EVIDENCE_CHANGED") == 1
    assert client.get("/v1/memory").json()["items"][0]["check"]["status"] == "verified"


def test_a10_export_then_delete_the_chain(api):
    client, _ = api.signup("a10@accounts.invalid")
    client.put("/v1/memory/consent", json={"consent": "granted"})
    client.put("/v1/profile/income", json={"salary_net": SALARY, "expected_version": 0})
    client.put("/v1/profile/income", json={"salary_net": {**SALARY, "amount": 1_300_000}, "expected_version": 1})
    card = _chat(client, "Ahora gano 1.400.000")["pending_memory_proposal"]
    assert len(client.get("/v1/memory/export").json()["declarations"]) == 2
    chain = client.get("/v1/memory").json()["items"][0]["chain_id"]
    assert client.delete(f"/v1/memory/{chain}").json() == {"chain_id": chain, "deleted_versions": 2, "revoked_proposals": 1}
    assert _confirm(client, card).json()["status"] == "PROPOSAL_STALE"
    assert client.get("/v1/memory/consent").json()["memory_revision"] == 3


def test_a11_account_deletion_takes_every_memory_record(api):
    client, user = api.signup("a11@accounts.invalid")
    other, other_user = api.signup("a11.other@accounts.invalid")
    for c in (client, other):
        c.put("/v1/memory/consent", json={"consent": "granted"})
        c.put("/v1/profile/income", json={"salary_net": SALARY, "expected_version": 0})
        assert _chat(c, "Ahora gano 1.300.000")["pending_memory_proposal"]
    erased = client.request("DELETE", "/v1/account", json={"confirm": "DELETE", "password": PASSWORD}).json()["erased"]
    assert (erased["user_memory"], erased["memory_state"], erased["memory_proposals"]) == (1, 1, 1)
    assert api.adapters.memory_store.for_user(user) == () and not api.services.memory.consent(user).granted
    assert len(other.get("/v1/memory/export").json()["declarations"]) == 1 and api.services.memory.consent(other_user).granted


FINANCIAL_READS = (
    ("GET", "/v1/state", None), ("GET", "/v1/commitments", None), ("GET", "/v1/protected-surplus", None), ("GET", "/v1/capacity", None),
    ("GET", "/v1/forecast?scenario=typical", None), ("GET", "/v1/forecast?scenario=conservative", None),
    ("GET", "/v1/forecast?scenario=stress", None), ("POST", "/v1/savings-plan", {}),
    ("POST", "/v1/simulate-purchase", {"amount": 600_000, "installments": 6}),
)


def test_a12_memory_changes_no_financial_number(api):
    client, _ = api.signup("a12@accounts.invalid")
    for f in SyntheticStatements().checking(21, date(2026, 9, 1), months=8, salary=1_100_000):
        assert client.post("/v1/statements", content=f.content).json()["status"] == "OK"
    assert client.get("/v1/me").json()["data_source"] == "statements"  # the account's own model, not a fixture

    def reads() -> list:
        return [client.request(method, path, json=body).json() for method, path, body in FINANCIAL_READS]

    before = reads()
    assert before[0]["status"] == "OK"
    client.put("/v1/memory/consent", json={"consent": "granted"})
    card = _chat(client, "Me subieron el sueldo a 1.500.000 desde noviembre")["pending_memory_proposal"]
    assert _confirm(client, card, salary_net={**SALARY, "amount": 1_500_000}, base={"amount": 1_100_000, "net": True, "effective_from": "2026-01"}).status_code == 200
    assert reads() == before
    client.delete(f"/v1/memory/{client.get('/v1/memory').json()['items'][0]['chain_id']}")
    assert reads() == before
