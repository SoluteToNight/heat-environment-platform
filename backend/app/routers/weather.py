"""Router: real weather + UTCI readings and warning alerts for arbitrary points.

Feeds the public landing card. Both endpoints are read-only, unauthenticated,
and cached server-side so visitor clusters share one upstream provider call.
"""

import logging

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas.common import make_api_response
from app.services.weather_alert_service import get_weather_alerts
from app.services.weather_point_service import WeatherFetchError, get_weather_point_forecast

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/weather", tags=["weather-point"])


@router.get("/point")
def get_point_weather(
    request: Request,
    longitude: float = Query(..., ge=-180.0, le=180.0, description="Longitude in degrees (East positive)"),
    latitude: float = Query(..., ge=-85.0, le=85.0, description="Latitude in degrees (North positive)"),
):
    """Real hourly weather with UTCI (sun & shade) for the given coordinate."""
    req_id = getattr(request.state, "request_id", "req_weather_point")
    try:
        data = get_weather_point_forecast(longitude=longitude, latitude=latitude)
    except WeatherFetchError as exc:
        logger.warning("Weather point fetch failed: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return make_api_response(data, req_id)


@router.get("/alerts")
def get_point_alerts(
    request: Request,
    longitude: float = Query(..., ge=-180.0, le=180.0, description="Longitude in degrees (East positive)"),
    latitude: float = Query(..., ge=-85.0, le=85.0, description="Latitude in degrees (North positive)"),
):
    """Real-time meteorological warning alerts for the given coordinate."""
    req_id = getattr(request.state, "request_id", "req_weather_alerts")
    data = get_weather_alerts(longitude=longitude, latitude=latitude)
    return make_api_response(data, req_id)
