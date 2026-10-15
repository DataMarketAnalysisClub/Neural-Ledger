from fastapi.testclient import TestClient

from neural_ledger.adapters.inbound.http.app import create_app


def test_profile_getter_is_user_scoped_and_unknown_is_insufficient(services):
    with TestClient(create_app(services)) as client:
        response = client.get("/v1/profile", headers={"X-User-Id": "diego"})
        assert response.status_code == 200
        assert response.json()["data"]["display_name"] == {"untrusted_text": "Diego"}
        assert client.get("/v1/profile", headers={"X-User-Id": "usr_missing"}).status_code == 409


def test_questionnaire_getter_and_no_write_routes(services):
    with TestClient(create_app(services)) as client:
        response = client.get("/v1/profile/questionnaire")
        assert response.status_code == 200
        assert response.json()["data"]["version"] == "pq-0.1"
        assert client.put("/v1/profile", json={"display_name": "Other"}).status_code == 405
        assert client.post("/v1/profile/questionnaire", json={}).status_code == 405
