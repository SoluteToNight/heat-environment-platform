"""Versioned weather ingestion from the configured provider."""
import datetime
import math
import uuid
import httpx
from typing import Optional
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import EnvRelease, WeatherRecord, utc_now


PRODUCT_SPECS = {
    "qweather": {
        "title": "和风天气逐小时预报",
        "source": "QWeather weather/v1/hourly",
        "variables": {"air_temperature", "relative_humidity", "wind_speed", "wind_direction"},
    },
    "open_meteo_ecmwf": {
        "model_name": "ecmwf_ifs025",
        "title": "ECMWF IFS 0.25° (Open-Meteo)",
        "source": "European Centre for Medium-Range Weather Forecasts via Open-Meteo",
    },
    "open_meteo_gfs": {
        "model_name": "gfs_seamless",
        "title": "NOAA GFS Seamless (Open-Meteo)",
        "source": "NOAA NCEP GFS via Open-Meteo",
    },
}


def configured_product_id():
    return settings.WEATHER_PROVIDER


def parse_rfc3339_utc(ts_str: str) -> datetime.datetime:
    """Parse ISO8601 string to timezone-aware UTC datetime."""
    # Open-Meteo returns '2026-09-16T00:00' when timezone=UTC
    if not ts_str.endswith("Z") and not ("+" in ts_str or "-" in ts_str[10:]):
        ts_str = ts_str + "Z"
    dt = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    return dt.astimezone(datetime.timezone.utc)


def generate_fallback_forecast(scene_id: str, product_id: str) -> dict:
    """Deterministic fallback in case of network unavailability during testing."""
    now = datetime.datetime.now(datetime.timezone.utc).replace(minute=0, second=0, microsecond=0)
    times = []
    temps = []
    rhs = []
    winds = []
    dirs = []
    gh = []
    dir_r = []
    diff_r = []
    dni = []

    for i in range(48):
        t = now + datetime.timedelta(hours=i)
        times.append(t.strftime("%Y-%m-%dT%H:%M"))
        # Solar hour angle approximation for diurnal cycle
        hour = (t.hour + 8) % 24  # Shanghai local hour
        solar_factor = max(0.0, math.sin(math.pi * (hour - 6) / 12)) if 6 <= hour <= 18 else 0.0
        
        temps.append(round(24.0 + 8.0 * solar_factor + 0.5 * math.sin(i), 1))
        rhs.append(round(85.0 - 35.0 * solar_factor, 1))
        winds.append(round(2.5 + 1.5 * math.cos(i / 3.0), 1))
        dirs.append(round((120.0 + 30.0 * math.sin(i / 2.0)) % 360, 1))
        gh.append(round(800.0 * solar_factor, 1))
        dir_r.append(round(550.0 * solar_factor, 1))
        diff_r.append(round(250.0 * solar_factor, 1))
        dni.append(round(700.0 * solar_factor, 1))

    return {
        "hourly": {
            "time": times,
            "temperature_2m": temps,
            "relative_humidity_2m": rhs,
            "wind_speed_10m": winds,
            "wind_direction_10m": dirs,
            "shortwave_radiation": gh,
            "direct_radiation": dir_r,
            "diffuse_radiation": diff_r,
            "direct_normal_irradiance": dni,
        },
        "hourly_units": {
            "temperature_2m": "°C",
            "relative_humidity_2m": "%",
            "wind_speed_10m": "m/s",
            "shortwave_radiation": "W/m²",
        },
        "is_fallback": True,
    }


def fetch_open_meteo_raw(product_id: str = "open_meteo_ecmwf") -> dict:
    """Fetch 48h hourly forecast from Open-Meteo without authentication."""
    model_param = PRODUCT_SPECS.get(product_id, {}).get("model_name", "ecmwf_ifs025")
    params = {
        "latitude": settings.SHANGHAI_CENTER_LAT,
        "longitude": settings.SHANGHAI_CENTER_LON,
        "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,shortwave_radiation,direct_radiation,diffuse_radiation,direct_normal_irradiance",
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m",
        "models": model_param,
        "wind_speed_unit": "ms",
        "timeformat": "iso8601",
        "timezone": "UTC",
    }
    try:
        with httpx.Client(timeout=settings.WEATHER_REQUEST_TIMEOUT_SECONDS) as client:
            resp = client.get(settings.OPEN_METEO_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            data["is_fallback"] = False
            return data
    except Exception as e:
        print(f"[Warning] Open-Meteo live request failed: {e}. Falling back to deterministic simulation.")
        return generate_fallback_forecast("scene_shanghai", product_id)


def sync_weather_release(
    db: Session,
    scene_id: str = "scene_shanghai",
    product_id: str | None = None,
    force: bool = False,
) -> EnvRelease:
    """Ingest latest forecast and persist as an EnvRelease snapshot."""
    product_id = product_id or configured_product_id()
    if product_id not in PRODUCT_SPECS:
        raise ValueError('Unknown weather product')
    # Check if a recent fresh release already exists (< 50 minutes old)
    now = utc_now()
    if not force:
        latest = (
            db.query(EnvRelease)
            .filter(EnvRelease.scene_id == scene_id, EnvRelease.product_id == product_id)
            .order_by(EnvRelease.computed_at.desc())
            .first()
        )
        if latest and (now - latest.computed_at).total_seconds() < 3000:
            return latest

    # Fetch raw data
    if product_id == 'qweather':
        from app.services.qweather_service import qweather_client
        raw_data = qweather_client.fetch_hourly()
    else:
        raw_data = fetch_open_meteo_raw(product_id)
    hourly = raw_data.get("hourly", {})
    times = hourly.get("time", [])
    if not times:
        raise ValueError("Weather data returned empty time array")

    dt_start = parse_rfc3339_utc(times[0])
    dt_end = parse_rfc3339_utc(times[-1])

    release_id = f"rel_{product_id}_{now.strftime('%Y%m%d%H%M')}_{uuid.uuid4().hex[:6]}"
    release = EnvRelease(
        id=release_id,
        scene_id=scene_id,
        product_id=product_id,
        model_source=PRODUCT_SPECS.get(product_id, {}).get("source", "Open-Meteo"),
        time_start=dt_start,
        time_end=dt_end,
        computed_at=now,
        freshness="fresh",
        availability="available",
        raw_meta={
            "units": raw_data.get("hourly_units", {}),
            "is_fallback": raw_data.get("is_fallback", False),
            "generation_time_ms": raw_data.get("generationtime_ms"),
            "latitude": raw_data.get('latitude', settings.SHANGHAI_CENTER_LAT),
            "longitude": raw_data.get('longitude', settings.SHANGHAI_CENTER_LON),
            **raw_data.get('provider_meta', {}),
        },
    )
    db.add(release)
    db.flush()

    # Insert WeatherRecord rows
    records = []
    temps = hourly.get("temperature_2m", [])
    rhs = hourly.get("relative_humidity_2m", [])
    winds = hourly.get("wind_speed_10m", [])
    dirs = hourly.get("wind_direction_10m", [])
    sws = hourly.get("shortwave_radiation", [])
    dirs_rad = hourly.get("direct_radiation", [])
    diffs = hourly.get("diffuse_radiation", [])
    dnis = hourly.get("direct_normal_irradiance", [])

    for idx, t_str in enumerate(times):
        rec = WeatherRecord(
            release_id=release_id,
            target_time=parse_rfc3339_utc(t_str),
            lon=raw_data.get('longitude', settings.SHANGHAI_CENTER_LON),
            lat=raw_data.get('latitude', settings.SHANGHAI_CENTER_LAT),
            temperature_2m=temps[idx] if idx < len(temps) else None,
            relative_humidity_2m=rhs[idx] if idx < len(rhs) else None,
            wind_speed_10m=winds[idx] if idx < len(winds) else None,
            wind_direction_10m=dirs[idx] if idx < len(dirs) else None,
            shortwave_radiation=sws[idx] if idx < len(sws) else None,
            direct_radiation=dirs_rad[idx] if idx < len(dirs_rad) else None,
            diffuse_radiation=diffs[idx] if idx < len(diffs) else None,
            direct_normal_irradiance=dnis[idx] if idx < len(dnis) else None,
        )
        records.append(rec)

    db.bulk_save_objects(records)
    db.commit()
    db.refresh(release)
    print(f"[Weather Ingest] Created release {release_id} with {len(records)} hourly records.")
    return release
