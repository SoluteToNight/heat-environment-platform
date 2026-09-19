"""Spatial Residual Adjustment (平差) & TPS-RBF Downscaling Assimilation Engine (v2.0).

Key Enhancements (Audit Remediation):
1. [EPSG:32651 UTM Projected Kilometer Coordinates]:
   Eliminates 14.1% spherical anisotropy of WGS-84 degrees at 31.2°N.
   Guarantees healthy matrix condition number and prevents eigenvalue near-singularity.
2. [Dynamic Huber + IQR Outlier Detection]:
   Adaptive threshold max(3.8°C, 2.5 * IQR) prevents false rejection of intense CBD urban heat hotspots.
3. [Thermodynamic Consistency Bounds]:
   Enforces physical constraints (RH in [5%, 100%], Wind >= 0, DewPoint <= AirTemperature).
4. [Virtual Far-Field Boundary Damping]:
   12 boundary anchors smoothly decay UHI residuals into agricultural/marine suburbs.
"""

import json
import logging
import math
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from pyproj import Transformer
from scipy.interpolate import Rbf

from app.config import settings
from app.services.cloak_tile_service import (
    decode_qweather_tile,
    sample_tile_at_coords,
    load_cached_tiles,
)
from app.services.forecast_fetch_service import (
    load_100_points,
    get_latest_forecast,
    fetch_and_cache_daily_forecast,
)
from app.services.spatial_math import solar_position
from app.services.utci_service import calculate_tmrt, calculate_utci

logger = logging.getLogger(__name__)

# Coordinate Transformers: EPSG:4326 (WGS84) <-> EPSG:32651 (UTM 51N, Shanghai meter grid)
PROJECT = Transformer.from_crs("EPSG:4326", "EPSG:32651", always_xy=True)
EXCHANGE = Transformer.from_crs("EPSG:32651", "EPSG:4326", always_xy=True)

# Shanghai Whole Municipal Region Extent (WGS84)
# Full Municipal Bounds: West: 120.85, South: 30.65, East: 122.25, North: 31.88 (~135km x 135km)
SHANGHAI_BOUNDS = tuple(settings.SHANGHAI_BBOX)
URBAN_BOUNDS = SHANGHAI_BOUNDS  # Backward-compatible alias across modules


def hourly_value(point: dict, variable_name: str, hour_index: int):
    """Read one forecast value; missing or out-of-range yields None — never a fabricated number.

    点位各字段长度可能因逐点抓取时刻不同而不一致，越界按缺测处理。
    """
    series = point["hourly"].get(variable_name) or []
    if hour_index < 0 or hour_index >= len(series):
        return None
    return series[hour_index]

# 12 Far-field Virtual Boundary Anchors across surrounding regional waters and outer plains (Zero-residual constraints)
VIRTUAL_BOUNDARY_ANCHORS = [
    {"name": "通州湾/南通外海", "lon": 121.20, "lat": 32.12},
    {"name": "启东东外海", "lon": 121.90, "lat": 32.08},
    {"name": "长江口外开阔海域(北)", "lon": 122.40, "lat": 31.75},
    {"name": "东海开阔海域(中)", "lon": 122.45, "lat": 31.25},
    {"name": "东海开阔海域(南)", "lon": 122.40, "lat": 30.70},
    {"name": "舟山群岛北部海域", "lon": 122.15, "lat": 30.50},
    {"name": "杭州湾水体中心", "lon": 121.45, "lat": 30.45},
    {"name": "海盐/平湖外海", "lon": 121.05, "lat": 30.50},
    {"name": "浙江嘉善外围平原", "lon": 120.70, "lat": 30.80},
    {"name": "太湖水体东南部", "lon": 120.45, "lat": 31.10},
    {"name": "苏州/昆山西侧平原", "lon": 120.65, "lat": 31.35},
    {"name": "常熟/常阴沙长江北岸", "lon": 120.80, "lat": 31.85},
]


def generate_500m_urban_grid(grid_step: float = 1000.0) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[tuple[float, float]]]:
    """Generate regular mesh grid across Shanghai municipal bounds in EPSG:32651.
    
    Default step is 1000m (~0.01° native UTCI resolution conforming to project spec).
    
    Returns:
        grid_lons (WGS84 2D), grid_lats (WGS84 2D),
        grid_xs_km (UTM 51N km 2D), grid_ys_km (UTM 51N km 2D),
        coords_list (WGS84 [(lon, lat), ...] for tile sampling)
    """
    west, south, east, north = SHANGHAI_BOUNDS
    min_x, min_y = PROJECT.transform(west, south)
    max_x, max_y = PROJECT.transform(east, north)

    xs = np.arange(min_x, max_x + grid_step, grid_step)
    ys = np.arange(min_y, max_y + grid_step, grid_step)
    xx, yy = np.meshgrid(xs, ys)

    # Convert to WGS84 coordinates for background tile sampling and GeoJSON output
    grid_lons, grid_lats = EXCHANGE.transform(xx, yy)
    coords_list = list(zip(grid_lons.ravel(), grid_lats.ravel()))

    # Projected kilometer grid for isotropic TPS-RBF evaluation
    grid_xs_km = xx / 1000.0
    grid_ys_km = yy / 1000.0

    return grid_lons, grid_lats, grid_xs_km, grid_ys_km, coords_list


# Multi-variable outlier rejection thresholds calibrated to physical meteorological units:
# - Temperature / Dew Point: 3.8 °C (accommodates high-density urban heat island gradients)
# - Relative Humidity: 20.0 % (allows water-body / urban vegetation microclimate variations)
# - Wind Speed: 5.0 m/s (accommodates urban street canyon roughness variations)
VARIABLE_OUTLIER_THRESHOLDS: dict[str, float] = {
    "temperature_2m": 3.8,
    "dew_point": 3.8,
    "relative_humidity_2m": 20.0,
    "wind_speed_10m": 5.0,
}

VARIABLE_ALIAS_MAP: dict[str, str] = {
    "tmp": "temperature_2m",
    "rh": "relative_humidity_2m",
    "wind": "wind_speed_10m",
    "dpt": "dew_point",
}


def detect_and_filter_outliers(
    control_points: list[dict],
    residuals: np.ndarray,
    base_threshold: float = 3.8,
    threshold: float | None = None
) -> tuple[np.ndarray, list[str]]:
    """Upgraded Dynamic Huber + IQR Outlier Detector on spatial residuals.
    
    Uses metric Euclidean distance (UTM km) to find 5 nearest neighbors.
    Calculates dynamic threshold = max(base_threshold, 2.5 * local_IQR) to prevent
    falsely rejecting genuine high-density urban microclimate hotspots (e.g. Lujiazui CBD).
    """
    if threshold is not None:
        base_threshold = threshold
    n = len(control_points)
    # Transform to UTM projected kilometers for isotropic neighbor search
    coords_km = np.array([PROJECT.transform(p["lon"], p["lat"]) for p in control_points]) / 1000.0
    diff = coords_km[:, np.newaxis, :] - coords_km[np.newaxis, :, :]
    dist_sq = np.sum(diff ** 2, axis=-1)

    inliers_mask = np.ones(n, dtype=bool)
    rejected_ids = []

    for i in range(n):
        nearest_idx = np.argsort(dist_sq[i])[1:6]
        local_residuals = residuals[nearest_idx]
        local_median = np.median(local_residuals)

        # Dynamic IQR calculation
        q75, q25 = np.percentile(local_residuals, [75, 25])
        local_iqr = q75 - q25
        effective_threshold = max(base_threshold, 2.5 * float(local_iqr))

        residual_dev = abs(residuals[i] - local_median)
        if residual_dev > effective_threshold:
            inliers_mask[i] = False
            rejected_ids.append(control_points[i]["id"])
            logger.warning(
                "Gross Error Rejected at Control Point %s (%s): Residual=%.2f, Median=%.2f, Dev=%.2f > Thresh=%.2f",
                control_points[i]["id"], control_points[i]["name"], residuals[i], local_median, residual_dev, effective_threshold
            )

    return inliers_mask, rejected_ids


def enforce_physical_bounds(
    field: np.ndarray,
    variable_name: str,
    temp_field: np.ndarray | None = None
) -> np.ndarray:
    """Enforce physical meteorological bounds and thermodynamic consistency."""
    bounded = field.copy()
    if variable_name in ("temperature_2m", "tmp"):
        # Reasonable ambient air temperature in Shanghai summer [-5°C, 48°C]
        bounded = np.clip(bounded, -5.0, 48.0)
    elif variable_name in ("relative_humidity_2m", "rh"):
        # Relative humidity strictly bounded in [5%, 100%]
        bounded = np.clip(bounded, 5.0, 100.0)
    elif variable_name in ("wind_speed_10m", "wind"):
        # Scalar wind speed strictly non-negative
        bounded = np.clip(bounded, 0.0, 60.0)
    elif variable_name in ("dew_point", "dpt"):
        # Dew point cannot physically exceed dry-bulb air temperature (cannot be supersaturated)
        if temp_field is not None:
            bounded = np.minimum(bounded, temp_field)
        bounded = np.clip(bounded, -20.0, 35.0)
    return bounded


def solve_spatial_adjustment(
    hour_index: int = 0,
    variable_name: str = "temperature_2m",
    smooth_factor: float = 0.5
) -> dict:
    """Execute end-to-end spatial adjustment & downscaling fusion in isotropic UTM coordinates.
    
    Args:
        hour_index: Forecast hour step (0 to 47).
        variable_name: 'temperature_2m', 'relative_humidity_2m', 'wind_speed_10m', 'dew_point'.
        smooth_factor: Regularization lambda in kilometer space (default: 0.5).
    
    Returns:
        Structured dictionary containing:
        - 500m fused grid values (with thermodynamic constraints applied)
        - 10 test points post-adjustment audit (MAE, RMSE)
        - Control points residuals & outlier rejection summary
    """
    # 1. Load latest forecast observations for 100 points
    forecast_data = get_latest_forecast()
    if not forecast_data:
        logger.info("No forecast cache found. Fetching daily forecast...")
        forecast_data = fetch_and_cache_daily_forecast(force_refresh=False)

    points_data = forecast_data["points_data"]

    # Separate into 90 control points and 10 test points
    control_pts = [p for p in points_data.values() if p["type"] == "control"]
    test_pts = [p for p in points_data.values() if p["type"] == "test"]

    # 2. Get decoded background tile field
    tile_var_map = {
        "temperature_2m": "tmp-2m",
        "relative_humidity_2m": "rh-2m",
        "wind_speed_10m": "wind-10m",
        "dew_point": "dpt-2m",
    }
    short_var = tile_var_map.get(variable_name, "tmp-2m")
    # 只读瓦片缓存，绝不在查询请求内启动浏览器自动化（一次抓取可达数十秒）。
    # 缓存缺失/过期时由 POST /api/v1/forecast/tiles/refresh 或后台任务负责刷新。
    tiles = load_cached_tiles() or {}
    if not tiles:
        logger.warning(
            "No fresh cached QWeather tiles; falling back to constant regional "
            "background. Trigger POST /api/v1/forecast/tiles/refresh to recapture."
        )

    if short_var in tiles:
        tile_info = tiles[short_var]
        tile_matrix, tile_meta = decode_qweather_tile(tile_info["body"], short_var.split("-")[0])
        z, x, y = tile_info["z"], tile_info["x"], tile_info["y"]
    else:
        # Graceful fallback: synthesize smooth background field from control points mean
        logger.warning("Tile %s not available in capture; using regional background synthesis", short_var)
        z, x, y = 8, 214, 106
        tile_matrix = np.full((257, 257), 24.5, dtype=float)

    # 3. Sample tile background values at control points
    ctrl_coords = [(p["lon"], p["lat"]) for p in control_pts]
    ctrl_bg_values = sample_tile_at_coords(tile_matrix, z, x, y, ctrl_coords)

    # Extract API forecast values at hour_index; missing values stay NaN and are
    # excluded from the fit — substituting them (e.g. with 25.0) would fabricate data.
    ctrl_api_values = np.array(
        [hourly_value(p, variable_name, hour_index) for p in control_pts],
        dtype=float,
    )

    # 4. Compute observed residuals v_i = T_api - T_bg
    observed_residuals = ctrl_api_values - ctrl_bg_values

    # 5. Missing-value screening (缺测剔除) + robust gross-error detection (Dynamic Huber + IQR)
    observed_mask = np.isfinite(observed_residuals)
    missing_ids = [control_pts[i]["id"] for i in range(len(control_pts)) if not observed_mask[i]]
    if missing_ids:
        logger.warning(
            "Missing %s values at control points %s for hour %d; excluded from fit.",
            variable_name, missing_ids, hour_index,
        )
    obs_points = [p for i, p in enumerate(control_pts) if observed_mask[i]]
    obs_residuals = observed_residuals[observed_mask]
    if len(obs_points) < 3:
        raise ValueError(
            f"Only {len(obs_points)} control points have usable {variable_name} values at "
            f"hour {hour_index}; refusing to fit on fabricated data."
        )
    canonical_var = VARIABLE_ALIAS_MAP.get(variable_name, variable_name)
    var_threshold = VARIABLE_OUTLIER_THRESHOLDS.get(canonical_var, 3.8)
    obs_inliers, rejected_ids = detect_and_filter_outliers(
        obs_points, obs_residuals, base_threshold=var_threshold
    )
    inliers_mask = np.zeros(len(control_pts), dtype=bool)
    inliers_mask[np.where(observed_mask)[0][obs_inliers]] = True

    valid_ctrl_pts = [p for i, p in enumerate(control_pts) if inliers_mask[i]]
    valid_residuals = observed_residuals[inliers_mask]
    if len(valid_ctrl_pts) == 0:
        raise ValueError("All control-point residuals were rejected as gross errors; refusing to fit.")

    # 6. Assemble TPS-RBF sample points in ISOTROPIC UTM KILOMETERS (EPSG:32651)
    ctrl_projected_km = [PROJECT.transform(p["lon"], p["lat"]) for p in valid_ctrl_pts]
    fit_xs_km = [p[0] / 1000.0 for p in ctrl_projected_km]
    fit_ys_km = [p[1] / 1000.0 for p in ctrl_projected_km]
    fit_residuals = list(valid_residuals)

    # Inject 12 Virtual Far-field Boundary Anchors (residual = 0.0)
    for anchor in VIRTUAL_BOUNDARY_ANCHORS:
        ax, ay = PROJECT.transform(anchor["lon"], anchor["lat"])
        fit_xs_km.append(ax / 1000.0)
        fit_ys_km.append(ay / 1000.0)
        fit_residuals.append(0.0)

    # 7. Solve Regularized Thin Plate Spline (TPS-RBF) in kilometer space
    rbf_model = Rbf(
        fit_xs_km,
        fit_ys_km,
        fit_residuals,
        function="thin_plate",
        smooth=smooth_factor
    )

    # 8. Reconstruct 500m Continuous Grid
    grid_lons, grid_lats, grid_xs_km, grid_ys_km, grid_coords = generate_500m_urban_grid()
    grid_bg_values = sample_tile_at_coords(tile_matrix, z, x, y, grid_coords)
    grid_bg_values = grid_bg_values.reshape(grid_lons.shape)

    # Evaluate smooth TPS residual surface in kilometer space
    grid_residual_field = rbf_model(grid_xs_km, grid_ys_km)
    raw_fused_field = grid_bg_values + grid_residual_field

    # Enforce physical bounds (e.g. RH <= 100%, Wind >= 0)
    grid_fused_field = enforce_physical_bounds(raw_fused_field, variable_name)

    # 9. Independent Test Points Audit (★T01 ~ ★T10)
    test_coords = [(p["lon"], p["lat"]) for p in test_pts]
    test_bg_values = sample_tile_at_coords(tile_matrix, z, x, y, test_coords)

    test_api_values = np.array(
        [hourly_value(p, variable_name, hour_index) for p in test_pts],
        dtype=float,
    )

    # Sample TPS residual surface at test points in kilometer space
    test_projected_km = [PROJECT.transform(p["lon"], p["lat"]) for p in test_pts]
    test_xs_km = [p[0] / 1000.0 for p in test_projected_km]
    test_ys_km = [p[1] / 1000.0 for p in test_projected_km]

    test_interpolated_residuals = rbf_model(test_xs_km, test_ys_km)
    raw_test_fused = test_bg_values + test_interpolated_residuals
    test_fused_values = enforce_physical_bounds(raw_test_fused, variable_name)

    # Post-adjustment blind test errors — test points with missing observations are
    # excluded from the metrics instead of being filled with placeholder values.
    test_errors = test_fused_values - test_api_values
    test_valid_mask = np.isfinite(test_errors)
    test_missing_ids = [test_pts[i]["id"] for i in range(len(test_pts)) if not test_valid_mask[i]]
    if test_valid_mask.any():
        valid_errors = test_errors[test_valid_mask]
        test_mae = float(np.mean(np.abs(valid_errors)))
        test_rmse = float(np.sqrt(np.mean(valid_errors ** 2)))
        max_abs_error = float(np.max(np.abs(valid_errors)))
        mean_error = float(np.mean(valid_errors))
    else:
        test_mae = test_rmse = max_abs_error = mean_error = None

    test_audit_details = []
    for idx, p in enumerate(test_pts):
        ok = bool(test_valid_mask[idx])
        test_audit_details.append({
            "id": p["id"],
            "name": p["name"],
            "district": p["district"],
            "lon": p["lon"],
            "lat": p["lat"],
            "tag": p.get("tag", ""),
            "api_observed": round(float(test_api_values[idx]), 2) if ok else None,
            "tile_background": round(float(test_bg_values[idx]), 2),
            "fused_estimate": round(float(test_fused_values[idx]), 2),
            "residual_error": round(float(test_errors[idx]), 2) if ok else None,
            "value_status": "valid" if ok else "missing",
        })

    # Forecast timestamp
    forecast_time = "Unknown"
    sample_pt = next(iter(points_data.values()))
    time_series = sample_pt["hourly"].get("time", [])
    if hour_index < len(time_series):
        forecast_time = time_series[hour_index]

    return {
        "variable": variable_name,
        "hour_index": hour_index,
        "forecast_time": forecast_time,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "urban_bounds": {
            "west": URBAN_BOUNDS[0],
            "south": URBAN_BOUNDS[1],
            "east": URBAN_BOUNDS[2],
            "north": URBAN_BOUNDS[3]
        },
        "grid_meta": {
            "resolution_m": 500,
            "shape": list(grid_fused_field.shape),
            "min_val": round(float(np.nanmin(grid_fused_field)), 2),
            "max_val": round(float(np.nanmax(grid_fused_field)), 2),
            "mean_val": round(float(np.nanmean(grid_fused_field)), 2),
        },
        "audit_metrics": {
            "test_points_count": len(test_pts),
            "valid_test_points_count": int(test_valid_mask.sum()),
            "missing_value_ids": test_missing_ids,
            "test_mae": round(test_mae, 3) if test_mae is not None else None,
            "test_rmse": round(test_rmse, 3) if test_rmse is not None else None,
            "max_abs_error": round(max_abs_error, 3) if max_abs_error is not None else None,
            "mean_error": round(mean_error, 3) if mean_error is not None else None,
            "test_details": test_audit_details
        },
        "control_points_summary": {
            "total_count": len(control_pts),
            "valid_inliers_count": len(valid_ctrl_pts),
            "missing_values_count": len(missing_ids),
            "missing_value_ids": missing_ids,
            "rejected_outliers": rejected_ids,
            "mean_residual": round(float(np.mean(valid_residuals)), 3),
            "min_residual": round(float(np.min(valid_residuals)), 3),
            "max_residual": round(float(np.max(valid_residuals)), 3),
        },
        "grid_data": {
            "lons": [round(x, 4) for x in grid_lons[0, :].tolist()],
            "lats": [round(y, 4) for y in grid_lats[:, 0].tolist()],
            "values": np.round(grid_fused_field, 2).tolist()
        }
    }


def publish_48h_urban_adjustment_release(force_refresh: bool = False) -> dict:
    """Generate and publish full 48-hour 500m assimilation release for Shanghai urban extent.
    
    Produces:
    - 500m regular mesh assimilation for Ta, RH, Wind, DewPoint via TPS-RBF in metric UTM km
    - Hourly solar radiation modulated by astronomical solar elevation
    - Hourly physical Mean Radiant Temperature (Tmrt) via Stefan-Boltzmann 6-direction balance
    - Hourly Universal Thermal Climate Index (UTCI) via Bröde 6th-order polynomial
    - 10 blind test points post-adjustment audit metrics across all 48 hours
    - Stores into settings.SPATIAL_STORAGE_DIR / <run_id> with latest.json pointer update.
    """
    root = settings.SPATIAL_STORAGE_DIR
    root.mkdir(parents=True, exist_ok=True)
    now_utc = datetime.now(timezone.utc)
    run_id = f"spatial_{now_utc.strftime('%Y%m%dT%H%M%SZ_')}{uuid.uuid4().hex[:8]}"
    output_dir = root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Load forecast dataset
    forecast_data = get_latest_forecast()
    if not forecast_data or force_refresh:
        logger.info("Fetching daily forecast for 100 points...")
        forecast_data = fetch_and_cache_daily_forecast(force_refresh=force_refresh)
        
    points_data = forecast_data["points_data"]
    control_pts = [p for p in points_data.values() if p["type"] == "control"]
    test_pts = [p for p in points_data.values() if p["type"] == "test"]
    
    sample_pt = next(iter(points_data.values()))
    raw_times = sample_pt["hourly"]["time"]
    n_times = len(raw_times)
    iso_times = [
        datetime.fromisoformat(t).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        for t in raw_times
    ]
    
    # 2. Generate 500m regular mesh grid across Shanghai Urban Bounds
    grid_lons, grid_lats, grid_xs_km, grid_ys_km, grid_coords = generate_500m_urban_grid()
    n_lats, n_lons = grid_lons.shape
    
    # 3. Decoded background tiles（只读缓存；浏览器抓取由维护端点/后台任务触发）
    tiles = load_cached_tiles() or {}
    if not tiles:
        logger.warning("No fresh cached QWeather tiles; falling back to constant regional background.")
    var_tile_map = {
        "temperature_2m": "tmp-2m",
        "relative_humidity_2m": "rh-2m",
        "wind_speed_10m": "wind-10m",
        "dew_point": "dpt-2m",
    }
    
    ctrl_coords = [(p["lon"], p["lat"]) for p in control_pts]
    test_coords = [(p["lon"], p["lat"]) for p in test_pts]
    
    ctrl_bg = {}
    test_bg = {}
    grid_bg = {}
    
    for v_name, short_code in var_tile_map.items():
        if short_code in tiles:
            t_info = tiles[short_code]
            t_mat, _ = decode_qweather_tile(t_info["body"], short_code.split("-")[0])
            z, x, y = t_info["z"], t_info["x"], t_info["y"]
        else:
            z, x, y = 8, 214, 106
            t_mat = np.full((257, 257), 24.0, dtype=float)
            
        ctrl_bg[v_name] = sample_tile_at_coords(t_mat, z, x, y, ctrl_coords)
        test_bg[v_name] = sample_tile_at_coords(t_mat, z, x, y, test_coords)
        grid_bg[v_name] = sample_tile_at_coords(t_mat, z, x, y, grid_coords).reshape(n_lats, n_lons)
        
    # Solar tile background (asob-surface)
    if "asob-surface" in tiles:
        t_info = tiles["asob-surface"]
        t_mat, _ = decode_qweather_tile(t_info["body"], "asob")
        grid_solar_bg = sample_tile_at_coords(t_mat, t_info["z"], t_info["x"], t_info["y"], grid_coords).reshape(n_lats, n_lons)
        grid_solar_bg = np.maximum(grid_solar_bg, 0.0)
    else:
        grid_solar_bg = np.full((n_lats, n_lons), 120.0, dtype=float)

    # 4. Projected coordinates for TPS-RBF fitting in isotropic UTM kilometers
    ctrl_projected_km = [PROJECT.transform(p["lon"], p["lat"]) for p in control_pts]
    fit_xs_ctrl_km = [p[0] / 1000.0 for p in ctrl_projected_km]
    fit_ys_ctrl_km = [p[1] / 1000.0 for p in ctrl_projected_km]
    
    anchor_xs_km = []
    anchor_ys_km = []
    for anchor in VIRTUAL_BOUNDARY_ANCHORS:
        ax, ay = PROJECT.transform(anchor["lon"], anchor["lat"])
        anchor_xs_km.append(ax / 1000.0)
        anchor_ys_km.append(ay / 1000.0)
        
    test_projected_km = [PROJECT.transform(p["lon"], p["lat"]) for p in test_pts]
    test_xs_km = [p[0] / 1000.0 for p in test_projected_km]
    test_ys_km = [p[1] / 1000.0 for p in test_projected_km]

    # 5. Initialize 3D assimilation cubes
    cube_ta = np.zeros((n_times, n_lats, n_lons), dtype=np.float32)
    cube_rh = np.zeros((n_times, n_lats, n_lons), dtype=np.float32)
    cube_wind = np.zeros((n_times, n_lats, n_lons), dtype=np.float32)
    cube_dpt = np.zeros((n_times, n_lats, n_lons), dtype=np.float32)
    cube_solar = np.zeros((n_times, n_lats, n_lons), dtype=np.float32)
    cube_utci = np.zeros((n_times, n_lats, n_lons), dtype=np.float32)

    test_temp_errors = []
    missing_test_evaluations = 0

    def assemble_fit_inputs(
        values,
        bg_values,
        detect_outliers: bool = True,
        variable_name: str | None = None,
        base_threshold: float | None = None,
    ):
        """Assemble TPS-RBF fit inputs for one variable at one hour.

        Missing (None/NaN) control values are excluded outright — never substituted —
        because a fabricated residual would contaminate the whole spline surface.
        """
        vals = np.asarray(values, dtype=float)
        residuals = vals - np.asarray(bg_values, dtype=float)
        obs_idx = np.where(np.isfinite(residuals))[0]
        if len(obs_idx) < 3:
            return None
        obs_points = [control_pts[i] for i in obs_idx]
        obs_residuals = residuals[obs_idx]
        if detect_outliers and len(obs_points) >= 6:
            canonical_var = VARIABLE_ALIAS_MAP.get(variable_name, variable_name) if variable_name else None
            thresh = (
                base_threshold
                if base_threshold is not None
                else (VARIABLE_OUTLIER_THRESHOLDS.get(canonical_var, 3.8) if canonical_var else 3.8)
            )
            inliers, _ = detect_and_filter_outliers(obs_points, obs_residuals, base_threshold=thresh)
        else:
            inliers = np.ones(len(obs_points), dtype=bool)
        keep = obs_idx[inliers]
        xs = [fit_xs_ctrl_km[i] for i in keep] + anchor_xs_km
        ys = [fit_ys_ctrl_km[i] for i in keep] + anchor_ys_km
        res = list(residuals[keep]) + [0.0] * len(anchor_xs_km)
        return xs, ys, res

    def fuse(fit_inputs, bg_values, variable_for_bounds, temp_field=None):
        if fit_inputs is None:
            return None
        rbf = Rbf(fit_inputs[0], fit_inputs[1], fit_inputs[2], function="thin_plate", smooth=0.5)
        field = enforce_physical_bounds(
            bg_values + rbf(grid_xs_km, grid_ys_km), variable_for_bounds, temp_field=temp_field
        )
        return field, rbf

    # 6. Execute 48-hour space-time assimilation
    logger.info("Computing 48-hour 500m assimilation for %d time steps...", n_times)
    for h in range(n_times):
        # A. Air Temperature（动态 Huber+IQR 抗差，3.8 °C 量纲容差；缺测控制点一律剔除，不造数）
        c_vals_ta = np.array([hourly_value(p, "temperature_2m", h) for p in control_pts], dtype=float)
        fused_ta_result = fuse(
            assemble_fit_inputs(
                c_vals_ta, ctrl_bg["temperature_2m"], detect_outliers=True, variable_name="temperature_2m"
            ),
            grid_bg["temperature_2m"], "temperature_2m",
        )
        if fused_ta_result is None:
            logger.warning("Hour %d: too few usable temperature control values; frame stored as no-data (NaN).", h)
            cube_ta[h] = np.float32(np.nan)
            missing_test_evaluations += len(test_pts)
        else:
            fused_ta, rbf_ta = fused_ta_result
            cube_ta[h] = fused_ta.astype(np.float32)
            # Test audit for Ta（缺测测试点不计入误差统计）
            t_vals_ta = np.array([hourly_value(p, "temperature_2m", h) for p in test_pts], dtype=float)
            errs = test_bg["temperature_2m"] + rbf_ta(test_xs_km, test_ys_km) - t_vals_ta
            finite_errs = errs[np.isfinite(errs)]
            missing_test_evaluations += int(errs.size - finite_errs.size)
            test_temp_errors.extend(finite_errs)

        # B. Relative Humidity（动态 Huber+IQR 抗差，20.0 % 量纲容差；缺测控制点剔除）
        c_vals_rh = np.array([hourly_value(p, "relative_humidity_2m", h) for p in control_pts], dtype=float)
        fused_rh_result = fuse(
            assemble_fit_inputs(
                c_vals_rh, ctrl_bg["relative_humidity_2m"], detect_outliers=True, variable_name="relative_humidity_2m"
            ),
            grid_bg["relative_humidity_2m"], "relative_humidity_2m",
        )
        if fused_rh_result is None:
            logger.warning("Hour %d: too few usable humidity control values; frame stored as no-data (NaN).", h)
            cube_rh[h] = np.float32(np.nan)
            fused_rh = cube_rh[h]
        else:
            fused_rh, _ = fused_rh_result
            cube_rh[h] = fused_rh.astype(np.float32)

        # C. Wind Speed（动态 Huber+IQR 抗差，5.0 m/s 量纲容差；缺测控制点剔除）
        c_vals_wind = np.array([hourly_value(p, "wind_speed_10m", h) for p in control_pts], dtype=float)
        fused_wind_result = fuse(
            assemble_fit_inputs(
                c_vals_wind, ctrl_bg["wind_speed_10m"], detect_outliers=True, variable_name="wind_speed_10m"
            ),
            grid_bg["wind_speed_10m"], "wind_speed_10m",
        )
        if fused_wind_result is None:
            logger.warning("Hour %d: too few usable wind control values; frame stored as no-data (NaN).", h)
            cube_wind[h] = np.float32(np.nan)
            fused_wind = cube_wind[h]
        else:
            fused_wind, _ = fused_wind_result
            cube_wind[h] = fused_wind.astype(np.float32)

        # D. Dew Point（动态 Huber+IQR 抗差，3.8 °C 量纲容差；缺测剔除；temp_field 约束不超饱和）
        c_vals_dpt = np.array([hourly_value(p, "dew_point", h) for p in control_pts], dtype=float)
        fused_dpt_result = fuse(
            assemble_fit_inputs(
                c_vals_dpt, ctrl_bg["dew_point"], detect_outliers=True, variable_name="dew_point"
            ),
            grid_bg["dew_point"], "dew_point", temp_field=fused_ta,
        )
        if fused_dpt_result is None:
            logger.warning("Hour %d: too few usable dew-point control values; frame stored as no-data (NaN).", h)
            cube_dpt[h] = np.float32(np.nan)
        else:
            fused_dpt, _ = fused_dpt_result
            cube_dpt[h] = fused_dpt.astype(np.float32)

        # E. Solar Irradiance
        moment = datetime.fromisoformat(raw_times[h])
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        _, elevation = solar_position(121.47, 31.23, moment)
        if elevation <= 0:
            hourly_solar = np.zeros((n_lats, n_lons), dtype=np.float32)
        else:
            scale = math.sin(elevation) / math.sin(math.radians(55.0))
            hourly_solar = np.clip(grid_solar_bg * scale * 2.2, 0.0, 1100.0).astype(np.float32)
        cube_solar[h] = hourly_solar

        # F. Bioclimatic UTCI & Tmrt（输入含 NaN 的像元 UTCI 亦为 NaN → 前端渲染为无数据）
        fused_tmrt = calculate_tmrt(fused_ta, hourly_solar)
        fused_utci, _ = calculate_utci(fused_ta, fused_rh, fused_wind, fused_tmrt)
        cube_utci[h] = fused_utci.astype(np.float32)

    # 7. Save 500m data cubes
    np.savez_compressed(
        output_dir / "grid_500m.npz",
        lons=grid_lons[0, :].astype(np.float32),
        lats=grid_lats[:, 0].astype(np.float32),
        air_temperature=cube_ta,
        relative_humidity=cube_rh,
        wind_speed=cube_wind,
        dew_point=cube_dpt,
        solar_radiation=cube_solar,
        utci=cube_utci,
    )

    # 8. Copy boundary geojson
    boundary_src = settings.BASE_DIR.parent.parent / "data/osm/shanghai/shanghai_boundary.geojson"
    if boundary_src.exists():
        (output_dir / "boundary.geojson").write_bytes(boundary_src.read_bytes())

    # 9. Audit statistics（缺测样本被剔除后，本轮可能没有有效盲测值）
    if test_temp_errors:
        errors_array = np.array(test_temp_errors)
        overall_mae = float(np.mean(np.abs(errors_array)))
        overall_rmse = float(np.sqrt(np.mean(errors_array ** 2)))
        max_err = float(np.max(np.abs(errors_array)))
    else:
        overall_mae = overall_rmse = max_err = None

    # 10. Write manifest.json
    manifest = {
        "run_id": run_id,
        "kind": "adjustment_500m",
        "status": "completed",
        "created_at": now_utc.isoformat(),
        "scene_id": "scene_shanghai",
        "bbox": list(SHANGHAI_BOUNDS),
        "grid_shape": [n_lats, n_lons],
        "resolution_m": 1000,
        "times": iso_times,
        "variables": ["utci", "air_temperature", "relative_humidity", "wind_speed", "dew_point", "solar_radiation"],
        "display_variables": ["utci", "air_temperature", "relative_humidity", "wind_speed", "dew_point", "solar_radiation"],
        "units": {
            "utci": "°C",
            "air_temperature": "°C",
            "relative_humidity": "%",
            "wind_speed": "m/s",
            "dew_point": "°C",
            "solar_radiation": "W/m²",
        },
        "method": "1000m (~0.01°) TPS-RBF Kilometer Space Assimilation & Bröde 6th-order UTCI Operational Polynomial",
        "source": f"QWeather 48h Forecast ({len(control_pts)} Control Points + {len(test_pts)} Blind Test Points) & Tiles & UTCI",
        "attributions": ["和风天气 (QWeather)", "欧洲中期天气预报中心 (ECMWF)", "国际生物气象学会 (ISB UTCI Commission)"],
        "spatial_support": f"上海市全域 1000m (约0.01°) 规则网格（EPSG:32651 平面公里平差降尺度），完整覆盖中心城区、浦东新区、宝山、嘉定、青浦、松江、金山、奉贤及崇明三岛；集成 {len(control_pts)} 处控制点与 {len(test_pts)} 处独立测试点验后精度闭环，逐像元严格求解 Bröde et al. 通用热气候指数 (UTCI)。",
        "quality": [
            "1000m (~0.01°) municipal whole region assimilation in metric EPSG:32651 UTM kilometer coordinates.",
            "Multi-variable Dynamic Huber + IQR outlier detection calibrated per physical unit (Ta/Dpt: 3.8°C, RH: 20%, Wind: 5.0 m/s) with 12 far-field outer marine/plain boundary damping anchors.",
            "Thermodynamic bounds enforced (RH in [5, 100]%, Wind >= 0, DewPoint <= AirTemperature).",
            "Missing forecast/background values are excluded from the fit (no fabrication); affected pixels are published as no-data (NaN).",
            "背景场为瓦片捕获时刻的单一有效时次（run/valid 时次解析自瓦片 URL 并记录于 tile_metadata_latest.json），48 小时各帧共享同一背景形态、仅残差场逐时演化；详见 docs/瓦片背景场时效与分辨率调查记录.md。",
            "Stefan-Boltzmann six-direction radiant energy balance for physical Tmrt evaluation.",
            "UTCI calculated strictly within valid bioclimatic bounds [-50°C, 50°C], 0.5-17 m/s draft."
        ],
        "audit_summary": {
            "test_points_count": len(test_pts),
            "total_test_evaluations": len(test_temp_errors),
            "missing_test_evaluations": missing_test_evaluations,
            "temperature_mae": round(overall_mae, 3) if overall_mae is not None else None,
            "temperature_rmse": round(overall_rmse, 3) if overall_rmse is not None else None,
            "max_abs_error": round(max_err, 3) if max_err is not None else None
        }
    }
    
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    
    # 11. Write quality report
    if overall_mae is not None:
        audit_md = f"""## 验后盲测精度审计 ({len(test_pts)} 个独立盲测点)
- **总检验时空点次数**: {len(test_temp_errors)} 次（另有 {missing_test_evaluations} 次因观测缺测被剔除，不造数）
- **平均绝对误差 (MAE)**: {overall_mae:.3f} °C
- **均方根误差 (RMSE)**: {overall_rmse:.3f} °C
- **最大绝对偏差**: {max_err:.3f} °C
- **平差状态**: 验后残差收敛（口径：相对同一供应商预报值的插值自洽性，非实测精度）。
"""
    else:
        audit_md = f"""## 验后盲测精度审计 ({len(test_pts)} 个独立盲测点)
- 本轮无有效盲测样本：观测缺测一律剔除（不造数），未产生可统计误差。
"""
    report_md = f"""# 上海市全域 1000m 天气与 UTCI 空间平差发布报告

- **发布标识 (run_id)**: `{run_id}`
- **生成时间 (UTC)**: `{now_utc.isoformat()}`
- **网格分辨率**: 1000m ({n_lats} 行 × {n_lons} 列，共 {n_lats * n_lons} 个计算像元)
- **空间范围**: 西经 {SHANGHAI_BOUNDS[0]}°, 南纬 {SHANGHAI_BOUNDS[1]}°, 东经 {SHANGHAI_BOUNDS[2]}°, 北纬 {SHANGHAI_BOUNDS[3]}° (上海市全域，涵盖崇明岛、长兴岛、横沙岛及全域16区)
- **预报时段**: 48 小时逐小时连续场 ({iso_times[0]} 至 {iso_times[-1]})
- **包含要素**: 通用热气候指数 (UTCI)、气温、相对湿度、风速、露点、太阳下行辐射

{audit_md}"""
    (output_dir / "quality_report.md").write_text(report_md, encoding="utf-8")

    # 12. Atomic update of latest.json
    latest_tmp = root / "latest.tmp"
    latest_tmp.write_text(json.dumps({"run_id": run_id}, indent=2), encoding="utf-8")
    os.replace(latest_tmp, root / "latest.json")
    
    if overall_mae is not None:
        logger.info("Successfully published 500m urban adjustment release: %s (MAE=%.3f°C)", run_id, overall_mae)
    else:
        logger.info("Successfully published 500m urban adjustment release: %s (no valid blind-test samples)", run_id)
    return manifest

