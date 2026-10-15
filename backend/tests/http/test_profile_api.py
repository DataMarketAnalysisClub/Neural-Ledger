from fastapi.testclient import TestClient

from neural_ledger.adapters.inbound.http.app import create_app
from neural_ledger.domain.audit.events import AuditKind


def test_profile_getter_is_user_scoped_and_unknown_is_insufficient(services):
    with TestClient(create_app(services)) as client:
        response = client.get("/v1/profile", headers={"X-User-Id": "diego"})
        assert response.status_code == 200
        assert response.json()["data"]["display_name"] == {"untrusted_text": "Diego"}
        assert client.get("/v1/profile", headers={"X-User-Id": "usr_missing"}).status_code == 409


def test_questionnaire_getter_and_no_write_routes(services, adapters):
    with TestClient(create_app(services)) as client:
        response = client.get("/v1/profile/questionnaire")
        assert response.status_code == 200
        assert response.json()["data"]["version"] == "pq-0.1"
        before = client.get("/v1/profile").json()
        write = client.put("/v1/profile", json={"display_name": "Other"})
        assert write.status_code == 403 and write.json()["status"] == "PROFILE_READ_ONLY"
        submit = client.post("/v1/profile/questionnaire", json={})
        assert submit.status_code == 403 and submit.json()["status"] == "PROFILE_READ_ONLY"
        assert client.get("/v1/profile").json() == before
        assert all(event.draft.kind is not AuditKind.PROFILE_UPDATED for event in adapters.audit_log.events())
