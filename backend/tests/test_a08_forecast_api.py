"""Integration tests for Forecast & Spatial Adjustment API routes."""

import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_get_forecast_quota():
    """Test /api/v1/forecast/quota returns valid quota statistics."""
    resp = client.get("/api/v1/forecast/quota")
    assert resp.status_code == 200
    data = resp.json()
    assert "data" in data
    quota = data["data"]
    assert quota["budget_limit"] == 5000
    assert quota["hard_cutoff_limit"] == 4800
    assert quota["total_used"] >= 100
    assert quota["remaining_quota"] <= 4900
    assert quota["is_blocked"] is False


def test_get_forecast_points():
    """Test /api/v1/forecast/points returns all points with series."""
    resp = client.get("/api/v1/forecast/points")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total_points"] == 144
    assert len(data["points"]) == 144
    # Check sample control point
    c01 = next(p for p in data["points"] if p["id"] == "C01")
    assert c01["name"] == "人民广场"
    assert c01["type"] == "control"
    assert "hourly" in c01
    assert len(c01["hourly"]["temperature_2m"]) == 48


def test_get_fused_grid():
    """Test /api/v1/forecast/grid returns mesh and audit metrics."""
    resp = client.get("/api/v1/forecast/grid?hour=0&variable=temperature_2m&smooth=0.08")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["variable"] == "temperature_2m"
    assert data["hour_index"] == 0
    assert "grid_meta" in data
    assert data["grid_meta"]["resolution_m"] in (500, 1000)
    assert data["grid_meta"]["shape"] == [136, 137]
    assert "audit_metrics" in data
    assert data["audit_metrics"]["test_mae"] > 0
    assert data["audit_metrics"]["test_rmse"] > 0
    assert len(data["audit_metrics"]["test_details"]) == 18


def test_get_audit_report():
    """Test /api/v1/forecast/audit returns summary metrics."""
    resp = client.get("/api/v1/forecast/audit?hour=3&variable=temperature_2m")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["hour_index"] == 3
    assert data["audit_metrics"]["test_points_count"] == 18
    assert data["control_points_summary"]["total_count"] == 126
