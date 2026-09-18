"""Tests for A02: Environment exploration, catalog, views, point and series queries."""
from fastapi.testclient import TestClient


def test_get_catalog(client: TestClient):
    resp = client.get("/api/v1/scenes/scene_shanghai/environment/catalog")
    assert resp.status_code == 200
    catalogs = resp.json()["data"]
    if isinstance(catalogs, dict):
        products = catalogs.get("products", [])
        var_codes = [p["variable"] for p in products]
        assert "air_temperature" in var_codes
    else:
        assert len(catalogs) >= 1
        cat = catalogs[0]
        var_codes = [v["code"] for v in cat["variables"]]
        assert "air_temperature" in var_codes


def test_list_releases(client: TestClient):
    resp = client.get("/api/v1/scenes/scene_shanghai/environment/releases")
    assert resp.status_code == 200
    releases = resp.json()["data"]
    assert len(releases) >= 1
    assert "release_id" in releases[0]
    assert releases[0]["freshness"] in ("fresh", "stale")


def test_create_and_query_fixed_view(client: TestClient):
    # 1. Create fixed view with "now"
    body = {
        "variables": ["air_temperature", "relative_humidity"],
        "time_selection": {"kind": "now"},
        "release_selection": {"mode": "latest"},
    }
    resp = client.post("/api/v1/scenes/scene_shanghai/environment/views", json=body)
    assert resp.status_code == 200
    v_data = resp.json()["data"]
    view_id = v_data["view_id"]
    assert view_id.startswith("view_") or view_id.startswith("sp_")

    # 2. Get view details
    get_resp = client.get(f"/api/v1/environment/views/{view_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["view_id"] == view_id

    # 3. Query point reading inside Shanghai
    pt_resp = client.get(f"/api/v1/environment/views/{view_id}/point?longitude=121.4737&latitude=31.2304")
    assert pt_resp.status_code == 200
    pt_data = pt_resp.json()["data"]
    raw_readings = pt_data.get("items") or pt_data.get("readings", [])
    readings = {r["variable"]: r for r in raw_readings}
    assert "air_temperature" in readings
    assert readings["air_temperature"]["value_status"] == "valid"
    assert isinstance(readings["air_temperature"]["value"], (int, float))

    # 4. Query point outside Shanghai -> outside_coverage / no_data
    out_resp = client.get(f"/api/v1/environment/views/{view_id}/point?longitude=110.0&latitude=20.0")
    assert out_resp.status_code == 200
    out_readings = out_resp.json()["data"].get("items") or out_resp.json()["data"].get("readings", [])
    assert all(r["value_status"] in ("outside_coverage", "no_data") for r in out_readings)
