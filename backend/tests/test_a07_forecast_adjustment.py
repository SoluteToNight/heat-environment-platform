"""Unit and integration tests for Forecast Quota Manager and Spatial Adjustment Engine."""

import numpy as np
import pytest
from app.services.forecast_quota_manager import (
    get_quota_status,
    can_consume,
    record_consumption,
    QuotaExceededException,
    GLOBAL_BUDGET_LIMIT,
    HARD_CUTOFF_LIMIT,
)
from app.services.spatial_adjustment_service import (
    generate_500m_urban_grid,
    detect_and_filter_outliers,
    solve_spatial_adjustment,
    VIRTUAL_BOUNDARY_ANCHORS,
)
from app.services.cloak_tile_service import decode_qweather_tile


def test_quota_manager_basic():
    """Verify quota tracking and safety guard."""
    status = get_quota_status()
    assert status["budget_limit"] == GLOBAL_BUDGET_LIMIT
    assert status["hard_cutoff_limit"] == HARD_CUTOFF_LIMIT
    assert status["is_blocked"] is False
    assert can_consume(100) is True


def test_outlier_detection_huber():
    """Verify 3-sigma Huber outlier detection filters gross errors."""
    mock_points = [
        {"id": f"C{i:02d}", "name": f"Pt{i}", "lon": 121.40 + (i % 5) * 0.05, "lat": 31.20 + (i // 5) * 0.05}
        for i in range(25)
    ]
    # Normal residuals around 1.5°C
    residuals = np.full(25, 1.5)
    # Inject gross errors at index 3 (+7.0°C) and index 12 (-5.0°C)
    residuals[3] = 8.5
    residuals[12] = -3.5

    inliers_mask, rejected_ids = detect_and_filter_outliers(mock_points, residuals, threshold=3.0)
    assert not inliers_mask[3]
    assert not inliers_mask[12]
    assert "C03" in rejected_ids
    assert "C12" in rejected_ids
    assert inliers_mask.sum() == 23


def test_500m_grid_generation():
    """Verify regular mesh grid dimensions and bounds across whole Shanghai."""
    grid_lons, grid_lats, grid_xs_km, grid_ys_km, coords = generate_500m_urban_grid()
    assert grid_lons.shape == grid_lats.shape
    assert grid_xs_km.shape == grid_ys_km.shape
    assert len(coords) == grid_lons.size
    # Check that grid coordinates cover full Shanghai municipal bounds
    assert 120.80 <= grid_lons.min() <= 120.90
    assert 122.20 <= grid_lons.max() <= 122.30
    assert 30.60 <= grid_lats.min() <= 30.70
    assert 31.80 <= grid_lats.max() <= 31.90


def test_virtual_anchors():
    """Verify 12 virtual boundary anchors are set up correctly around Shanghai municipal boundary."""
    assert len(VIRTUAL_BOUNDARY_ANCHORS) == 12
    for anchor in VIRTUAL_BOUNDARY_ANCHORS:
        assert "lon" in anchor and "lat" in anchor and "name" in anchor
        # Outside municipal perimeter, in regional outer waters and plains
        assert 120.40 <= anchor["lon"] <= 122.50
        assert 30.40 <= anchor["lat"] <= 32.20
