"""Pytest fixtures and configuration."""
import pytest
from fastapi.testclient import TestClient

from app.db.init_db import init_platform_db
from app.db.session import SessionLocal
from app.main import app
from app.services.weather_service import sync_weather_release


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """Ensure database schema, seed users, and initial weather release exist."""
    init_platform_db()
    db = SessionLocal()
    try:
        sync_weather_release(db)
    finally:
        db.close()


@pytest.fixture(scope="module")
def client():
    """FastAPI test client."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def user_auth_headers(client: TestClient) -> dict[str, str]:
    """Login as standard user and return authorization header."""
    resp = client.post("/api/v1/auth/login", json={"username": "user_test", "password": "user123456"})
    assert resp.status_code == 200
    session_id = resp.json()["data"]["session_id"]
    return {"Authorization": f"Bearer {session_id}"}


@pytest.fixture(scope="module")
def admin_auth_headers(client: TestClient) -> dict[str, str]:
    """Login as admin user and return authorization header."""
    resp = client.post("/api/v1/auth/login", json={"username": "admin_test", "password": "admin123456"})
    assert resp.status_code == 200
    session_id = resp.json()["data"]["session_id"]
    return {"Authorization": f"Bearer {session_id}"}
