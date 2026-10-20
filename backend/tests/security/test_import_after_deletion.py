"""An account deletion is terminal for a statement import that is still running (G03, ADR-048 §8).

An import reads, redacts and classifies outside any write, then commits with a token. A request authenticated before
its account was deleted must not recreate anything for it: not when the deletion lands before the import takes its
first token, not between the token and the commit, and not before a retry takes a new one. The owner check runs inside
the commit's transaction, the import ends as unauthenticated (never retried), and no import event is appended for the
erased owner. Another user's data stays as it was; a normal import and an enabled demo persona's import still work.
Both persistence adapters; synthetic data only.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from neural_ledger.adapters.inbound.http.app import create_app
from neural_ledger.application.ports import AccountGone, ImportCommit
from neural_ledger.bootstrap.container import build
from neural_ledger.domain.audit.events import AuditKind
from tests.conftest import make_settings
from tests.statement_samples import santander_xlsx

pytestmark = pytest.mark.security

ORIGIN = "http://localhost:3000"
KEY = "5c" * 32
PASSWORD = "synthetic-password-imp"
# A second, different cartola (another month): new for every user, so a commit for an erased owner would recreate it.
LATER = santander_xlsx(period=("30/09/2026", "31/10/2026"))
IMPORT_KINDS = {AuditKind.STATEMENT_IMPORTED, AuditKind.MEMORY_EVIDENCE_CHANGED}


class World:
    def __init__(self, persistence: str, tmp_path: Path) -> None:
        extra = {"persistence": "sqlite", "sqlite_path": str(tmp_path / "imp.db"), "data_key": KEY} if persistence == "sqlite" else {}
        self.services, self.adapters = build(make_settings(auth="accounts", app_origins=(ORIGIN,), **extra))
        self._app = create_app(self.services, cors_origins=(ORIGIN,))
        self.ana_client, self.ana = self.signup("ana.import@accounts.invalid")
        self.bea_client, self.bea = self.signup("bea.import@accounts.invalid")
        for user in (self.ana, self.bea):  # memory on, so an import also derives evidence transitions
            assert self.services.memory.set_consent(user, "s1", {"consent": "granted"}).ok
            assert self.services.memory.declare_from_profile(
                user, "s1", {"salary_net": {"amount": 1_100_000, "net": True, "effective_from": "2026-09"}, "expected_version": 0}
            ).ok

    def client(self) -> TestClient:
        return TestClient(self._app, headers={"Origin": ORIGIN})

    def signup(self, email: str) -> tuple[TestClient, str]:
        client = self.client()
        response = client.post(
            "/v1/auth/signup", json={"email": email, "password": PASSWORD, "display_name": "Synthetic", "sandbox_acknowledged": True}
        )
        assert response.status_code == 201, response.text
        assert client.post("/v1/statements", content=santander_xlsx()).json()["status"] == "OK"
        return client, response.json()["user_id"]

    def delete(self, client: TestClient) -> None:
        response = client.request("DELETE", "/v1/account", json={"password": PASSWORD, "confirm": "DELETE"})
        assert response.status_code == 200 and response.json()["status"] == "DELETED", response.text

    def owned(self, user_id: str) -> tuple:
        """Everything an import or memory could have recreated for a user, and the user's own audit events."""
        s = self.services
        events = tuple(e for e in self.adapters.audit_log.events() if e.draft.user_id == user_id)
        return (
            s.statements._store.for_user(user_id), s.statements._transactions.for_user(user_id),
            self.adapters.memory_store.for_user(user_id), self.adapters.memory_writes.state(user_id), events,
        )

    def hook(self, *, before_token=None, after_token=None, before_commit=None) -> list[ImportCommit]:
        """Wrap the import's writes: a side effect before or after the n-th token, or before the n-th commit (1-based)."""
        real = self.services.statements._writes
        tokens, outcomes = [0], []

        class Hooked:
            def token(self, user_id: str) -> str:
                tokens[0] += 1
                if before_token and tokens[0] in before_token:
                    before_token[tokens[0]]()
                value = real.token(user_id)
                if after_token and tokens[0] in after_token:
                    after_token[tokens[0]]()
                return value

            def commit(self, user_id, token, statements, transactions, events):
                if before_commit and len(outcomes) + 1 in before_commit:
                    before_commit[len(outcomes) + 1]()
                outcome = real.commit(user_id, token, statements, transactions, events)
                outcomes.append(outcome)
                return outcome

        self.services.statements._writes = Hooked()
        return outcomes


@pytest.fixture(params=["memory", "sqlite"])
def world(request, tmp_path) -> World:
    return World(request.param, tmp_path)


def _assert_erased(world: World, bea_before: tuple) -> None:
    statements, transactions, declarations, state, events = world.owned(world.ana)
    assert (statements, transactions, declarations) == ((), (), ())
    assert (state.consent_generation, state.memory_revision) == (0, 0)  # no memory state recreated either
    assert [e for e in events if e.draft.kind in IMPORT_KINDS] == []
    assert world.owned(world.bea)[:4] == bea_before[:4]  # the other user's rows are untouched
    assert [e.draft.event_id for e in world.owned(world.bea)[4]] == [e.draft.event_id for e in bea_before[4]]


def test_a_deletion_before_the_first_token_ends_the_import_with_nothing_stored(world):
    bea_before = world.owned(world.bea)
    world.delete(world.ana_client)  # the request below was authenticated before the deletion
    outcomes = world.hook()
    with pytest.raises(AccountGone):
        world.services.statements.import_statement(world.ana, LATER)
    assert outcomes == [ImportCommit.OWNER_GONE]
    _assert_erased(world, bea_before)


def test_a_deletion_between_the_token_and_the_commit_recreates_nothing(world):
    bea_before = world.owned(world.bea)
    outcomes = world.hook(after_token={1: lambda: world.delete(world.ana_client)})
    with pytest.raises(AccountGone):
        world.services.statements.import_statement(world.ana, LATER)
    assert outcomes == [ImportCommit.OWNER_GONE]  # checked in the commit's transaction, before the token
    _assert_erased(world, bea_before)


def test_a_deletion_before_a_retry_is_terminal_not_another_retry(world):
    bea_before = world.owned(world.bea)

    def concurrent_change() -> None:  # a write between the first token and its commit: the first attempt must retry
        assert world.services.memory.set_consent(world.ana, "s1", {"consent": "revoked"}).ok

    # The first attempt's commit finds a changed token; the account is deleted before the retry takes its own.
    outcomes = world.hook(before_commit={1: concurrent_change}, before_token={2: lambda: world.delete(world.ana_client)})
    with pytest.raises(AccountGone):
        world.services.statements.import_statement(world.ana, LATER)
    assert outcomes == [ImportCommit.CHANGED, ImportCommit.OWNER_GONE]  # one retry, then terminal: no third attempt
    _assert_erased(world, bea_before)


def test_the_import_route_answers_unauthenticated_and_stores_nothing(world):
    bea_before = world.owned(world.bea)
    late = world.client()
    late.cookies = world.ana_client.cookies  # the same session, authenticated before the deletion lands
    world.hook(after_token={1: lambda: world.delete(world.ana_client)})
    response = late.post("/v1/statements", content=LATER)
    assert response.status_code == 401 and response.json()["status"] == "UNAUTHENTICATED"
    _assert_erased(world, bea_before)


def test_normal_and_enabled_demo_persona_imports_still_commit(world):
    reply = world.ana_client.post("/v1/statements", content=LATER).json()
    assert reply["status"] == "OK" and not reply["data"]["imports"][0]["duplicate"]
    visitor = world.client()
    assert visitor.post("/v1/auth/demo-session", json={"persona": "camila"}).status_code == 200
    assert visitor.post("/v1/statements", content=santander_xlsx()).json()["status"] == "OK"
    assert world.services.statements._store.for_user("camila")


def test_an_unknown_owner_is_refused_in_accounts_mode_and_kept_in_demo_mode(tmp_path):
    services, _ = build(make_settings(auth="accounts", app_origins=(ORIGIN,)))
    with pytest.raises(AccountGone):  # not an account, not an enabled persona: no permissive fallback
        services.statements.import_statement("usr_never_existed", santander_xlsx())
    assert services.statements._store.for_user("usr_never_existed") == ()
    demo, _ = build(make_settings())  # demo mode has no accounts: its owners are the header's, as before
    assert demo.statements.import_statement("valentina", santander_xlsx()).ok
