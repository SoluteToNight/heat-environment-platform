"""Point Weather & UTCI Service for the public landing card.

Fetches real hourly forecasts for an arbitrary coordinate from Open-Meteo
(free tier, no API key) and converts them into bioclimatic thermal-stress
readings with the exact same code path used by the map and decision dashboard:
``app.services.utci_service`` (pythermalcomfort UTCI polynomial, Bröde et al. 2012).

Design notes
------------
- Coordinates are rounded to a ~1.1 km grid and responses are cached in memory
  (15 min TTL) so many visitors sharing a neighbourhood share one provider call.
- All datetimes returned by Open-Meteo are location-local wall times (ISO strings
  without offset); they are display strings only and are never stored.
- Failures raise ``WeatherFetchError`` and are surfaced as HTTP 503 — the card
  must show an honest "数据暂不可用" state, never fabricated numbers.
"""

import logging
import time
import threading
from datetime import datetime, timezone

import httpx

from app.services.utci_service import calculate_tmrt, calculate_utci, classify_utci_chinese

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
COORD_PRECISION = 2          # ~1.1 km grid
CACHE_TTL_SECONDS = 900      # 15 minutes
FORECAST_DAYS = 3            # -> 72 hourly records, card renders 48h window


class WeatherFetchError(RuntimeError):
    """Raised when the upstream weather provider cannot be reached or parsed."""


_cache: dict[tuple[float, float], tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def _round_coord(value: float) -> float:
    return round(float(value), COORD_PRECISION)


def _cache_key(longitude: float, latitude: float) -> tuple[float, float]:
    return (_round_coord(longitude), _round_coord(latitude))


def _fetch_open_meteo(longitude: float, latitude: float, transport=None) -> dict:
    params = {
        "latitude": f"{latitude:.4f}",
        "longitude": f"{longitude:.4f}",
        "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,shortwave_radiation",
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,shortwave_radiation",
        "wind_speed_unit": "ms",
        "forecast_days": str(FORECAST_DAYS),
        "timezone": "auto",
    }
    try:
        with httpx.Client(timeout=12.0, transport=transport, follow_redirects=False) as client:
            response = client.get(OPEN_METEO_URL, params=params)
    except httpx.RequestError as exc:
        raise WeatherFetchError("天气数据服务商连接失败或超时。") from exc
    if response.status_code != 200:
        raise WeatherFetchError(f"天气数据服务商返回 HTTP {response.status_code}。")
    try:
        payload = response.json()
    except ValueError:
        raise WeatherFetchError("天气数据服务商返回了无效 JSON。") from None
    hourly = payload.get("hourly") or {}
    required = ("time", "temperature_2m", "relative_humidity_2m", "wind_speed_10m", "shortwave_radiation")
    if any(not hourly.get(name) for name in required):
        raise WeatherFetchError("天气数据服务商未返回完整的小时序列。")
    return payload


def _stress(value: float) -> dict:
    zh, en, color = classify_utci_chinese(value)
    return {"zh": zh, "en": en, "color": color}


def _build_reading(time_str: str, ta: float, rh: float, wind: float, solar: float) -> dict:
    """Assemble a single UTCI reading; shade assumes no shortwave load (Tmrt = Ta)."""
    ta = float(ta)
    rh = float(rh)
    wind = float(wind)
    solar = max(float(solar or 0.0), 0.0)
    tmrt = calculate_tmrt(ta_c=ta, solar_rad_w_m2=solar)
    utci_sun, _ = calculate_utci(ta_c=ta, rh_percent=rh, wind_speed_m_s=wind, tmrt_c=tmrt)
    utci_shade, _ = calculate_utci(ta_c=ta, rh_percent=rh, wind_speed_m_s=wind, tmrt_c=ta)
    return {
        "time": time_str,
        "air_temperature_c": round(ta, 1),
        "relative_humidity_pct": round(rh),
        "wind_speed_ms": round(wind, 1),
        "shortwave_radiation_wm2": round(solar),
        "tmrt_c": round(tmrt, 1),
        "utci_c": round(utci_sun, 1),
        "utci_shade_c": round(utci_shade, 1),
        "stress": _stress(utci_sun),
    }


def get_weather_point_forecast(longitude: float, latitude: float, transport=None, clock=time.time) -> dict:
    """Return current + hourly UTCI readings for a coordinate (cached)."""
    key = _cache_key(longitude, latitude)
    now = clock()
    with _cache_lock:
        cached = _cache.get(key)
        if cached and now - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]

    payload = _fetch_open_meteo(key[0], key[1], transport=transport)
    hourly = payload["hourly"]
    current = payload.get("current") or {}

    try:
        readings = [
            _build_reading(time_str, ta, rh, wind, solar)
            for time_str, ta, rh, wind, solar in zip(
                hourly["time"],
                hourly["temperature_2m"],
                hourly["relative_humidity_2m"],
                hourly["wind_speed_10m"],
                hourly["shortwave_radiation"],
                strict=True,
            )
        ]
    except (TypeError, ValueError) as exc:
        raise WeatherFetchError("天气数据包含缺测值，无法计算 UTCI。") from exc

    # Anchor "now" to the current wall-clock hour of the queried location
    current_time = str(current.get("time") or readings[0]["time"])[:13]
    now_index = next((i for i, r in enumerate(readings) if r["time"][:13] == current_time), 0)

    window = readings[now_index:now_index + 48]
    peak = max(window, key=lambda r: r["utci_c"], default=None)

    data = {
        "location": {"longitude": key[0], "latitude": key[1], "grid_rounded": True},
        "timezone": payload.get("timezone"),
        "utc_offset_seconds": payload.get("utc_offset_seconds"),
        "source": {
            "provider": "Open-Meteo",
            "utci_model": "UTCI polynomial approximation (Bröde et al. 2012, via pythermalcomfort)",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
        "now_index": now_index,
        "current": readings[now_index],
        "hourly": readings,
        "peak": {"utci_c": peak["utci_c"], "time": peak["time"]} if peak else None,
    }

    with _cache_lock:
        if len(_cache) > 512:
            _cache.clear()
        _cache[key] = (now, data)
    return data
