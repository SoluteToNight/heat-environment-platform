"""FastAPI Router for Weather Forecast Multi-Source Spatial Adjustment & Post-Audit."""

import logging
from typing import Literal
from fastapi import APIRouter, HTTPException, Query, Request
from app.schemas.common import make_api_response

from app.services.forecast_quota_manager import (
    get_quota_status,
    QuotaExceededException,
)
from app.services.forecast_fetch_service import (
    get_latest_forecast,
    fetch_and_cache_daily_forecast,
    load_100_points,
)
from app.services.spatial_adjustment_service import solve_spatial_adjustment

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/forecast", tags=["forecast-adjustment"])


@router.get("/quota")
def get_forecast_quota(request: Request):
    """Retrieve QWeather API quota consumption and cutoff guard status."""
    req_id = getattr(request.state, "request_id", "req_quota")
    return make_api_response(get_quota_status(), req_id)


@router.get("/points")
def get_forecast_points(request: Request):
    """Retrieve 100 control and test points with their latest 48-hour forecast series."""
    req_id = getattr(request.state, "request_id", "req_points")
    forecast = get_latest_forecast()
    if not forecast:
        points = load_100_points()
        data = {
            "cached": False,
            "total_points": len(points),
            "points": points
        }
    else:
        data = {
            "cached": True,
            "fetch_time": forecast.get("fetch_time"),
            "date": forecast.get("date"),
            "total_points": forecast.get("total_points"),
            "success_count": forecast.get("success_count"),
            "points": list(forecast.get("points_data", {}).values())
        }
    return make_api_response(data, req_id)


@router.get("/grid")
def get_fused_grid(
    request: Request,
    hour: int = Query(0, ge=0, le=47, description="Forecast hour offset (0 to 47)"),
    variable: Literal[
        "temperature_2m", "relative_humidity_2m", "wind_speed_10m", "dew_point"
    ] = Query("temperature_2m", description="Meteorological variable"),
    smooth: float = Query(0.5, ge=0.001, le=5.0, description="TPS-RBF smoothing lambda in km")
):
    """Compute and retrieve 500m fused grid and independent test points audit metrics."""
    req_id = getattr(request.state, "request_id", "req_grid")
    try:
        result = solve_spatial_adjustment(
            hour_index=hour,
            variable_name=variable,
            smooth_factor=smooth
        )
        return make_api_response(result, req_id)
    except Exception as exc:
        logger.error("Spatial adjustment computation error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Adjustment computation failed: {exc}")


@router.get("/audit")
def get_audit_report(
    request: Request,
    hour: int = Query(0, ge=0, le=47, description="Forecast hour offset (0 to 47)"),
    variable: str = Query("temperature_2m")
):
    """Retrieve post-adjustment accuracy audit (MAE/RMSE) on 10 independent test points."""
    req_id = getattr(request.state, "request_id", "req_audit")
    try:
        res = solve_spatial_adjustment(hour_index=hour, variable_name=variable)
        data = {
            "variable": res["variable"],
            "hour_index": res["hour_index"],
            "forecast_time": res["forecast_time"],
            "audit_metrics": res["audit_metrics"],
            "control_points_summary": res["control_points_summary"]
        }
        return make_api_response(data, req_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/sync")
def sync_forecast(
    request: Request,
    force: bool = Query(False, description="Force refresh API calls ignoring daily cache")
):
    """Trigger 100-point daily forecast sync and spatial adjustment cache update."""
    req_id = getattr(request.state, "request_id", "req_sync")
    try:
        data = fetch_and_cache_daily_forecast(force_refresh=force)
        quota = get_quota_status()
        res = {
            "success": True,
            "date": data.get("date"),
            "success_points": data.get("success_count"),
            "total_points": data.get("total_points"),
            "quota_status": quota
        }
        return make_api_response(res, req_id)
    except QuotaExceededException as qe:
        raise HTTPException(status_code=429, detail=str(qe))
    except Exception as exc:
        logger.error("Sync error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
