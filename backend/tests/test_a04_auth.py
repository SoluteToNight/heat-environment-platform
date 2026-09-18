"""Tests for A04: Identity, authentication, sessions, and logout."""
from fastapi.testclient import TestClient


def test_auth_lifecycle(client: TestClient):
    # 1. Bad credentials
    bad_resp = client.post("/api/v1/auth/login", json={"username": "user_test", "password": "wrong_password"})
    assert bad_resp.status_code == 401
    assert "Invalid username or password" in bad_resp.json()["error"]["message"]

    # 2. Login success
    login_resp = client.post("/api/v1/auth/login", json={"username": "user_test", "password": "user123456"})
    assert login_resp.status_code == 200
    login_data = login_resp.json()["data"]
    assert login_data["is_authenticated"] is True
    assert login_data["user"]["username"] == "user_test"
    session_id = login_data["session_id"]

    # 3. Check session info via Header
    sess_resp = client.get("/api/v1/auth/session", headers={"Authorization": f"Bearer {session_id}"})
    assert sess_resp.status_code == 200
    assert sess_resp.json()["data"]["is_authenticated"] is True
    assert sess_resp.json()["data"]["user"]["username"] == "user_test"

    # 4. Logout
    logout_resp = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {session_id}"})
    assert logout_resp.status_code == 204

    # 5. Session after logout
    sess_after = client.get("/api/v1/auth/session", headers={"Authorization": f"Bearer {session_id}"})
    assert sess_after.status_code == 200
    assert sess_after.json()["data"]["is_authenticated"] is False
