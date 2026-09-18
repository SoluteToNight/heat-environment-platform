"""Tests for A06: Export job creation, status polling, and CSV download."""
import uuid
from fastapi.testclient import TestClient


def test_export_my_check_ins(client: TestClient, user_auth_headers: dict):
    # 1. Post export request
    body = {
        "export_type": "my_check_ins",
        "file_format": "csv",
        "scene_id": "scene_shanghai",
    }
    resp = client.post(
        "/api/v1/exports",
        json=body,
        headers={**user_auth_headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 202
    data = resp.json()["data"]
    export_id = data["export_id"]
    task_id = data["task_id"]
    assert export_id.startswith("exp_")
    assert task_id.startswith("task_")

    # 2. Check export status
    status_resp = client.get(f"/api/v1/exports/{export_id}", headers=user_auth_headers)
    assert status_resp.status_code == 200
    status_data = status_resp.json()["data"]
    assert status_data["export_id"] == export_id

    # Since background tasks execute synchronously in TestClient, status is ready
    assert status_data["status"] == "ready"
    assert status_data["file_size_bytes"] > 0
    assert status_data["sha256_hash"] is not None

    # 3. Download export file
    dl_resp = client.get(f"/api/v1/exports/{export_id}/download", headers=user_auth_headers)
    assert dl_resp.status_code == 200
    assert "text/csv" in dl_resp.headers["Content-Type"]
    # Check UTF-8-SIG BOM
    content = dl_resp.content
    assert content.startswith(b"\xef\xbb\xbf")


def test_export_environment_table(client: TestClient, user_auth_headers: dict):
    # 1. Create a view first
    view_resp = client.post(
        "/api/v1/scenes/scene_shanghai/environment/views",
        json={
            "variables": ["air_temperature", "relative_humidity"],
            "time_selection": {"kind": "now"},
            "release_selection": {"mode": "latest"},
        },
    )
    assert view_resp.status_code == 200
    view_id = view_resp.json()["data"]["view_id"]

    # 2. Export environment table
    exp_resp = client.post(
        "/api/v1/exports",
        json={
            "export_type": "environment_table",
            "file_format": "csv",
            "view_id": view_id,
            "scene_id": "scene_shanghai",
        },
        headers={**user_auth_headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert exp_resp.status_code == 202
    exp_id = exp_resp.json()["data"]["export_id"]
    task_id = exp_resp.json()["data"]["task_id"]

    # 3. Check task status endpoint directly
    task_resp = client.get(f"/api/v1/tasks/{task_id}", headers=user_auth_headers)
    assert task_resp.status_code == 200
    task_data = task_resp.json()["data"]
    assert task_data["task_id"] == task_id
    assert task_data["status"] == "success"

    # 4. Download file
    dl_resp = client.get(f"/api/v1/exports/{exp_id}/download", headers=user_auth_headers)
    assert dl_resp.status_code == 200
    assert b"target_time_utc" in dl_resp.content

