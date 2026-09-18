"""Tests for A01: Scene and layer catalog, places, and features."""
from fastapi.testclient import TestClient


def test_list_scenes(client: TestClient):
    resp = client.get("/api/v1/scenes")
    assert resp.status_code == 200
    res = resp.json()
    assert "data" in res
    assert "meta" in res
    assert len(res["data"]) >= 1
    assert any(s["id"] == "scene_shanghai" for s in res["data"])


def test_get_scene_detail(client: TestClient):
    resp = client.get("/api/v1/scenes/scene_shanghai")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == "scene_shanghai"
    assert data["name"] == "上海市全域热暴露场景"
    assert len(data["bbox"]) == 4


def test_get_scene_layers(client: TestClient):
    resp = client.get("/api/v1/scenes/scene_shanghai/layers")
    assert resp.status_code == 200
    layers = resp.json()["data"]
    assert len(layers) >= 5
    layer_ids = [l["layer_id"] for l in layers]
    assert "layer_admin" in layer_ids
    assert "layer_buildings" in layer_ids
    assert "layer_roads" in layer_ids


def test_search_places(client: TestClient):
    resp = client.get("/api/v1/scenes/scene_shanghai/places?limit=10")
    assert resp.status_code == 200
    places = resp.json()["data"]
    assert isinstance(places, list)
    if places:
        assert "title" in places[0]
        assert "lon" in places[0]
        assert "lat" in places[0]


def test_query_features(client: TestClient):
    resp = client.get("/api/v1/scenes/scene_shanghai/features?layer_id=layer_admin&limit=5")
    assert resp.status_code == 200
    features = resp.json()["data"]
    assert len(features) >= 1
    first_feat = features[0]
    assert first_feat["layer_id"] == "layer_admin"
    assert "geometry" in first_feat
    assert "properties" in first_feat
