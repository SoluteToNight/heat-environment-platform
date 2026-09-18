"""Tests for A05: Scene status, ETag/304 caching, and tasks."""
from fastapi.testclient import TestClient


def test_scene_status_and_etag(client: TestClient):
    # 1. First fetch
    resp1 = client.get("/api/v1/scenes/scene_shanghai/status")
    assert resp1.status_code == 200
    assert "ETag" in resp1.headers
    etag = resp1.headers["ETag"]
    data = resp1.json()["data"]
    assert data["scene_id"] == "scene_shanghai"
    assert data["update_state"] in ("idle", "running")

    # 2. Conditional request with If-None-Match -> 304 Not Modified
    resp2 = client.get("/api/v1/scenes/scene_shanghai/status", headers={"If-None-Match": etag})
    assert resp2.status_code == 304
