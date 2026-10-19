"""S19 (D9): the agent can read the profile (T0) but never write it or its tolerance. Writes are user-only HTTP flows."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from neural_ledger.adapters.inbound.http.app import create_app
from neural_ledger.application.conversation import ToolCall
from neural_ledger.application.services.tools import ToolContext
from neural_ledger.bootstrap.container import build
from neural_ledger.domain.audit.events import Actor, AuditKind
from neural_ledger.domain.permissions.policy import PROHIBITED_CAPABILITIES, BlockReason, Tier
from tests.conftest import make_settings

pytestmark = pytest.mark.security
NAMES = ("update_user_profile", "set_risk_tolerance", "submit_questionnaire", "update_profile")
ORIGIN = "http://localhost:5173"
SESSION = "s19"


def _system(auth: str):
    return build(make_settings(auth=auth, app_origins=(ORIGIN,)))


@pytest.mark.parametrize("name", NAMES)
def test_s19_profile_write_names_are_prohibited_self_escalation(name):
    assert PROHIBITED_CAPABILITIES[name] is BlockReason.SELF_ESCALATION


@pytest.mark.parametrize("auth", ["demo", "accounts"])
@pytest.mark.parametrize("name", NAMES)
def test_s19_registry_blocks_profile_writes_as_t3_and_changes_nothing(auth, name):
    services, adapters = _system(auth)
    assert name not in services.registry.names
    before = services.profiles.user_profile("camila")
    arguments = {"display_name": "Escalated", "tolerance": "aggressive", "declared_tolerance": "aggressive"}
    outcome = services.registry.invoke(ToolCall(f"c_{name}", name, arguments), ToolContext(SESSION, "camila"), max_tier=Tier.T2, allow_stateful=True)
    assert outcome.blocked_reason == BlockReason.SELF_ESCALATION.value and outcome.tier is Tier.T3
    event = adapters.audit_log.events()[-1].draft
    assert event.kind is AuditKind.ACTION_BLOCKED and event.actor is Actor.AGENT
    assert event.permission_tier == "T3" and event.tool_requested == name and event.blocked_reason == "SELF_ESCALATION"
    assert services.profiles.user_profile("camila") == before
    assert all(e.draft.kind is not AuditKind.PROFILE_UPDATED for e in adapters.audit_log.events())


@pytest.mark.parametrize("body", [
    {"declared_tolerance": "aggressive"},
    {"display_name": "Ana", "declared_tolerance": "aggressive"},
    {"language": "en", "questionnaire": []},
    {"display_name": "Ana", "questionnaire_version": "pq-0.1"},
    {"tolerance": "aggressive"},
])
def test_s19_user_profile_write_rejects_tolerance_and_unknown_fields_without_echo(body):
    services, adapters = _system("accounts")
    client = TestClient(create_app(services), headers={"Origin": ORIGIN})
    signup = client.post("/v1/auth/signup", json={"email": "s19@accounts.invalid", "password": "synthetic-password-123", "display_name": "Ana", "sandbox_acknowledged": True})
    assert signup.status_code == 201
    before = client.get("/v1/profile").json()
    events = adapters.audit_log.events()
    response = client.put("/v1/profile", json=body)
    assert response.status_code == 422
    assert response.json() == {"status": "INVALID_INPUT", "message": "invalid input", "field": "body"}
    assert "aggressive" not in response.text and "questionnaire" not in response.text and "tolerance" not in response.text
    assert client.get("/v1/profile").json() == before
    assert adapters.audit_log.events() == events
