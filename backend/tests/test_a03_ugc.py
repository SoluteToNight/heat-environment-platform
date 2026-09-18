"""Tests for A03: UGC check-in, privacy coarsening, idempotency, revision control, and aggregation."""
import datetime
import uuid
from fastapi.testclient import TestClient


def test_create_check_in_and_idempotency(client: TestClient, user_auth_headers: dict):
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    idemp_key = f"key_{uuid.uuid4().hex}"

    body = {
        "scene_id": "scene_shanghai",
        "location": {"type": "Point", "coordinates": [121.4737, 31.2304]},
        "experienced_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "thermal_sensation": "hot",
        "thermal_comfort": "uncomfortable",
        "setting": "outdoor",
        "activity": "walking",
        "sun_exposure": "direct_sun",
        "note": "步行在南京东路，阳光强烈感觉很热",
        "visibility": "public",
        "public_location_precision": "grid_200m",
    }

    # 1. Create first time -> 201
    headers = {**user_auth_headers, "Idempotency-Key": idemp_key}
    resp1 = client.post("/api/v1/check-ins", json=body, headers=headers)
    assert resp1.status_code == 201
    data1 = resp1.json()["data"]
    chk_id = data1["id"]
    assert data1["revision"] == 1
    assert data1["visibility"] == "public"

    # Verify grid coarsening: coarse coordinates must differ slightly from exact coordinates
    assert data1["exact_location"]["coordinates"] == [121.4737, 31.2304]
    assert data1["public_location"]["coordinates"] != [121.4737, 31.2304]

    # 2. Resubmit with identical key and body -> returns same record
    resp2 = client.post("/api/v1/check-ins", json=body, headers=headers)
    assert resp2.status_code == 201
    assert resp2.json()["data"]["id"] == chk_id

    # 3. Resubmit with same key but different body -> 409 Conflict
    body_diff = {**body, "thermal_sensation": "cold"}
    resp3 = client.post("/api/v1/check-ins", json=body_diff, headers=headers)
    assert resp3.status_code == 409


def test_validation_errors(client: TestClient, user_auth_headers: dict):
    # Future time > 5 min
    future_time = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    body_future = {
        "location": {"type": "Point", "coordinates": [121.4737, 31.2304]},
        "experienced_at": future_time,
        "thermal_sensation": "warm",
    }
    resp = client.post("/api/v1/check-ins", json=body_future, headers={**user_auth_headers, "Idempotency-Key": str(uuid.uuid4())})
    assert resp.status_code == 422

    # Outside Shanghai boundary
    now_time = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body_outside = {
        "location": {"type": "Point", "coordinates": [114.0, 30.0]},
        "experienced_at": now_time,
        "thermal_sensation": "warm",
    }
    resp_out = client.post("/api/v1/check-ins", json=body_outside, headers={**user_auth_headers, "Idempotency-Key": str(uuid.uuid4())})
    assert resp_out.status_code == 422


def test_public_view_and_revision_control(client: TestClient, user_auth_headers: dict):
    now_time = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    idemp_key = str(uuid.uuid4())
    body = {
        "location": {"type": "Point", "coordinates": [121.48, 31.24]},
        "experienced_at": now_time,
        "thermal_sensation": "warm",
        "visibility": "public",
        "note": "微风，感觉偏热",
    }

    create_resp = client.post("/api/v1/check-ins", json=body, headers={**user_auth_headers, "Idempotency-Key": idemp_key})
    assert create_resp.status_code == 201
    chk_id = create_resp.json()["data"]["id"]

    # 1. Anonymous / public detail view: owner_id and exact location must NOT be exposed
    client.cookies.clear()
    pub_detail = client.get(f"/api/v1/check-ins/{chk_id}")
    assert pub_detail.status_code == 200
    pub_data = pub_detail.json()["data"]
    assert "owner_id" not in pub_data
    assert "exact_location" not in pub_data
    assert "location" in pub_data

    # Owner detail view: full fields including owner_id
    owner_detail = client.get(f"/api/v1/check-ins/{chk_id}", headers=user_auth_headers)
    assert owner_detail.status_code == 200
    owner_data = owner_detail.json()["data"]
    assert "owner_id" in owner_data
    assert "exact_location" in owner_data

    # 2. PATCH without If-Match -> 428 Precondition Required
    patch_resp1 = client.patch(f"/api/v1/check-ins/{chk_id}", json={"note": "更新后的备注"}, headers=user_auth_headers)
    assert patch_resp1.status_code == 428

    # 3. PATCH with mismatched If-Match -> 412 Precondition Failed
    patch_resp2 = client.patch(
        f"/api/v1/check-ins/{chk_id}",
        json={"note": "更新后的备注"},
        headers={**user_auth_headers, "If-Match": '"999"'},
    )
    assert patch_resp2.status_code == 412

    # 4. PATCH with valid If-Match -> 200, revision becomes 2
    patch_resp3 = client.patch(
        f"/api/v1/check-ins/{chk_id}",
        json={"note": "更新后的备注"},
        headers={**user_auth_headers, "If-Match": '"1"'},
    )
    assert patch_resp3.status_code == 200
    assert patch_resp3.json()["data"]["revision"] == 2

    # 5. Query public list
    pub_list = client.get(
        f"/api/v1/check-ins?scene_id=scene_shanghai&bbox=120.0,30.0,123.0,32.0&start_time=2026-09-01T00:00:00Z&end_time=2026-09-30T00:00:00Z"
    )
    assert pub_list.status_code == 200
    assert any(item["id"] == chk_id for item in pub_list.json()["data"])

    # 6. DELETE with valid If-Match ("2") -> 204 No Content
    del_resp = client.delete(f"/api/v1/check-ins/{chk_id}", headers={**user_auth_headers, "If-Match": '"2"'})
    assert del_resp.status_code == 204

    # 7. Deleted item must no longer be found
    assert client.get(f"/api/v1/check-ins/{chk_id}").status_code == 404


def test_aggregates_and_reports(client: TestClient, user_auth_headers: dict):
    now_time = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. Create a public check-in
    body = {
        "location": {"type": "Point", "coordinates": [121.47, 31.23]},
        "experienced_at": now_time,
        "thermal_sensation": "hot",
        "visibility": "public",
    }
    create_resp = client.post("/api/v1/check-ins", json=body, headers={**user_auth_headers, "Idempotency-Key": str(uuid.uuid4())})
    assert create_resp.status_code == 201
    chk_id = create_resp.json()["data"]["id"]

    # 2. Query aggregates
    aggs_resp = client.get(
        "/api/v1/check-ins/aggregates?scene_id=scene_shanghai&bbox=121.0,31.0,122.0,32.0&start_time=2026-09-01T00:00:00Z&end_time=2026-09-30T00:00:00Z"
    )
    assert aggs_resp.status_code == 200
    aggs = aggs_resp.json()["data"]
    assert len(aggs) >= 1
    assert "grid_id" in aggs[0]
    assert "total_count" in aggs[0]
    assert "sensation_counts" in aggs[0]

    # 3. Report check-in
    report_resp = client.post(
        f"/api/v1/check-ins/{chk_id}/reports",
        json={"reason": "内容测试举报反馈"},
        headers={**user_auth_headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert report_resp.status_code == 201
    assert "report_id" in report_resp.json()["data"]

