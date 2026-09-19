"""Integration tests for 24h UTCI & subjective heat perception inversion API."""

import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_24h_forecast_summary():
    response = client.get("/api/v1/forecast/24h/summary")
    assert response.status_code == 200
    json_data = response.json()
    assert "data" in json_data
    assert "meta" in json_data
    data = json_data["data"]
    assert "forecast_24h_overview" in data
    assert "hourly_details" in data
    assert len(data["hourly_details"]) > 0
    assert "ugc_validation_metrics" in data
    assert data["ugc_validation_metrics"]["accuracy_optimal"] >= 0.85


def test_24h_spatial_grid():
    response = client.get("/api/v1/forecast/24h/grid?lead_hour=5")
    assert response.status_code == 200
    json_data = response.json()
    assert "data" in json_data
    geojson = json_data["data"]
    assert geojson.get("type") == "FeatureCollection"
    assert len(geojson.get("features", [])) > 0


def test_24h_extreme_regions():
    response = client.get("/api/v1/forecast/24h/extreme_regions?lead_hour=5")
    assert response.status_code == 200
    json_data = response.json()
    assert "data" in json_data
    data = json_data["data"]
    assert "top_extreme_hotspots" in data
    assert len(data["top_extreme_hotspots"]) <= 10


def test_24h_decision_support():
    response = client.get("/api/v1/forecast/24h/decision")
    assert response.status_code == 200
    json_data = response.json()
    assert "data" in json_data
    data = json_data["data"]
    assert "active_alerts" in data
    assert "sector_guidelines" in data


def test_models_evaluation():
    response = client.get("/api/v1/models/evaluation")
    assert response.status_code == 200
    json_data = response.json()
    assert "data" in json_data
    data = json_data["data"]
    assert "model_version" in data
    assert "metrics_table" in data
    assert "coefficients_table" in data
    assert data["test_2024_m1_auc"] > 0.70


def test_custom_inversion():
    payload = {
        "air_temperature_c": 35.0,
        "relative_humidity_pct": 65.0,
        "wind_speed_10m_ms": 2.0,
        "net_solar_radiation_wm2": 450.0,
        "green_fraction": 0.15,
        "water_fraction": 0.05,
        "building_fraction": 0.25,
    }
    response = client.post("/api/v1/forecast/custom_inversion", json=payload)
    assert response.status_code == 200
    json_data = response.json()
    assert "data" in json_data
    data = json_data["data"]
    assert "calculated_utci_c" in data
    assert "p_hot_base" in data
    assert "p_hot_enhanced" in data
    assert "risk_level" in data
    assert data["risk_level"] in ["low", "moderate", "high", "extreme"]


def test_map_figure_access():
    response = client.get("/api/v1/forecast/24h/maps/01_model_coefficients_odds_ratios.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert len(response.content) > 1000
