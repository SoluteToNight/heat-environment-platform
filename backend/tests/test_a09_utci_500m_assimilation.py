"""Unit and Integration Tests for 500m Urban Adjustment Assimilation & UTCI Bioclimatic Service."""

import pytest
import numpy as np
from fastapi.testclient import TestClient

from app.services.utci_service import calculate_tmrt, calculate_utci, classify_utci_chinese
from app.services import spatial_service as spatial


def test_utci_service_physics_equations():
    """Verify physical thermodynamic equations for Tmrt and UTCI."""
    # 1. At nighttime (solar radiation = 0), Tmrt should equal air temperature
    ta_night = 25.0
    tmrt_night = calculate_tmrt(ta_night, 0.0)
    assert abs(tmrt_night - ta_night) < 0.01

    # 2. Under midday sunshine (solar radiation = 600 W/m²), Tmrt should significantly exceed Ta
    ta_day = 32.0
    tmrt_day = calculate_tmrt(ta_day, 600.0)
    assert tmrt_day > ta_day + 10.0
    assert tmrt_day < ta_day + 30.0

    # 3. Calculate UTCI under hot sunny summer conditions
    # Ta = 32°C, RH = 65%, Wind = 1.5 m/s, Tmrt = 48°C
    utci_hot, stress_hot = calculate_utci(ta_day, 65.0, 1.5, tmrt_day)
    assert utci_hot > 32.0
    zh, en, col = classify_utci_chinese(utci_hot)
    assert "热应激" in zh

    # 4. Vectorized evaluation
    ta_vec = np.array([22.0, 28.0, 35.0])
    rad_vec = np.array([0.0, 300.0, 700.0])
    tmrt_vec = calculate_tmrt(ta_vec, rad_vec)
    utci_vec, stress_vec = calculate_utci(ta_vec, np.array([75.0, 60.0, 50.0]), np.array([2.0, 1.5, 1.0]), tmrt_vec)
    assert len(utci_vec) == 3
    assert utci_vec[0] < utci_vec[1] < utci_vec[2]


def test_spatial_catalog_includes_utci(client: TestClient):
    """Verify that the spatial catalog publishes UTCI as a first-class environmental variable."""
    resp = client.get("/api/v1/scenes/scene_shanghai/environment/catalog")
    assert resp.status_code == 200
    data = resp.json()["data"]
    products = data.get("products", data if isinstance(data, list) else [])
    var_list = [p.get("variable") or p.get("code") for p in products]
    assert "utci" in var_list
    assert "air_temperature" in var_list


def test_utci_view_and_raster_generation(client: TestClient):
    """Verify view creation, 500m raster PNG generation, point query, and series query for UTCI."""
    # 1. Create a spatial view containing UTCI
    body = {
        "variables": ["utci", "air_temperature", "relative_humidity"],
        "time_selection": {"kind": "now"},
        "release_selection": {"mode": "latest"},
    }
    view_resp = client.post("/api/v1/scenes/scene_shanghai/environment/views", json=body)
    assert view_resp.status_code == 200
    v_data = view_resp.json()["data"]
    view_id = v_data["view_id"]
    assert view_id.startswith("sp_")
    
    utci_item = next((it for it in v_data["items"] if it["variable"] == "utci"), None)
    assert utci_item is not None
    assert utci_item["availability"] == "available"
    assert len(utci_item["assets"]) > 0
    
    asset = utci_item["assets"][0]
    raster_url = asset["url"]
    
    # 2. Fetch the generated raster PNG
    png_resp = client.get(raster_url)
    assert png_resp.status_code == 200
    assert png_resp.headers["content-type"] == "image/png"
    assert len(png_resp.content) > 1000  # Valid PNG image bytes
    
    # 3. Query point reading in Shanghai metropolitan core (People's Square: 121.4737°E, 31.2304°N)
    pt_resp = client.get(f"/api/v1/environment/views/{view_id}/point?longitude=121.4737&latitude=31.2304")
    assert pt_resp.status_code == 200
    pt_items = pt_resp.json()["data"]["items"]
    utci_reading = next(it for it in pt_items if it["variable"] == "utci")
    assert utci_reading["value_status"] == "valid"
    assert 10.0 <= utci_reading["value"] <= 50.0
    
    # 4. Query 48-hour time series for UTCI
    series_resp = client.get(f"/api/v1/spatial/views/{view_id}/series?longitude=121.4737&latitude=31.2304&variable=utci")
    assert series_resp.status_code == 200
    series_data = series_resp.json()["data"]
    assert series_data["variable"] == "utci"
    assert len(series_data["points"]) == 48
    assert all(pt["value"] is not None for pt in series_data["points"])
