"""Hourly Weather Forecast Fetch Service for Shanghai Audit Points.

Fetches rolling 48-hour hourly weather forecasts (temperature, humidity, wind, dew point)
for 126 Control Points + 18 Independent Test Points (144 total, see
``shanghai_audit_points_100.json``), with built-in daily caching, rate limiting, and
strict quota guard protection. Quota accounting counts every issued HTTP request
(including failures and retries), since the provider bills per request.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.config import settings
from app.services.forecast_quota_manager import (
    can_consume,
    record_consumption,
    QuotaExceededException,
)
from app.services.qweather_service import QWeatherClient, QWeatherError

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CACHE_DIR = DATA_DIR / "forecast_cache"
POINTS_FILE = DATA_DIR / "shanghai_audit_points_100.json"
LATEST_CACHE_FILE = CACHE_DIR / "forecast_100pts_latest.json"


def load_100_points() -> list[dict]:
    """Load the verified 100 points configuration."""
    if not POINTS_FILE.exists():
        raise FileNotFoundError(f"Points config not found at {POINTS_FILE}")
    with open(POINTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("points", [])


def get_latest_forecast() -> dict | None:
    """Retrieve the most recent forecast from cache without consuming API quota."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if LATEST_CACHE_FILE.exists():
        try:
            with open(LATEST_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Failed to read latest forecast cache: %s", e)
    
    # Fallback to finding latest daily cache file
    cached_files = sorted(CACHE_DIR.glob("forecast_100pts_20*.json"), reverse=True)
    if cached_files:
        try:
            with open(cached_files[0], "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Failed to read fallback forecast cache: %s", e)
    return None


def _fetch_single_point(pt: dict, client: QWeatherClient, http_client: httpx.Client | None = None) -> tuple[dict, dict | None, int]:
    """Fetch 48h forecast for a single point with retry and attempts tracking."""
    pt_id = pt["id"]
    lat = pt["lat"]
    lon = pt["lon"]
    hourly_data = None
    attempts = 0

    for attempt in range(2):
        attempts += 1
        try:
            res = client.fetch_hourly(latitude=lat, longitude=lon, http_client=http_client)
            hourly_data = res.get("hourly")
            break
        except Exception as exc:
            logger.warning("Point %s (Attempt %d) failed: %s", pt_id, attempt + 1, exc)
            time.sleep(0.2)

    return pt, hourly_data, attempts


def fetch_and_cache_daily_forecast(force_refresh: bool = False) -> dict:
    """Fetch 48h hourly forecast for all 100 points and cache to disk.
    
    If today's cache already exists and force_refresh is False, returns the cached copy
    to preserve user API quota.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    today_cache_file = CACHE_DIR / f"forecast_100pts_{today_str}.json"

    if today_cache_file.exists() and not force_refresh:
        logger.info("Found existing forecast cache for %s, skipping API calls.", today_str)
        with open(today_cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    points = load_100_points()
    total_pts = len(points)
    if total_pts == 0:
        raise ValueError("No points defined in shanghai_audit_points_100.json")

    # Quota check
    if not can_consume(total_pts):
        raise QuotaExceededException(
            f"Cannot fetch {total_pts} points: API quota limit would be exceeded."
        )

    logger.info("Initiating daily forecast fetch for %d points (Today: %s)", total_pts, today_str)
    client = QWeatherClient(settings)
    try:
        client.token()
    except Exception as exc:
        logger.warning("Pre-warming QWeather JWT token failed: %s", exc)

    points_data = {}
    success_count = 0
    fail_count = 0
    attempt_count = 0

    max_workers = min(6, total_pts)
    logger.info("Using ThreadPoolExecutor with %d workers and pooled HTTP keep-alive to fetch %d points", max_workers, total_pts)
    with httpx.Client(
        timeout=settings.WEATHER_REQUEST_TIMEOUT_SECONDS,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        follow_redirects=False,
    ) as http_client:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_fetch_single_point, pt, client, http_client): pt for pt in points}
            for future in as_completed(futures):
                pt, hourly_data, attempts = future.result()
                attempt_count += attempts
                pt_id = pt["id"]
                if hourly_data:
                    points_data[pt_id] = {
                        "id": pt_id,
                        "name": pt["name"],
                        "district": pt["district"],
                        "type": pt["type"],
                        "lon": pt["lon"],
                        "lat": pt["lat"],
                        "tag": pt.get("tag", ""),
                        "hourly": hourly_data
                    }
                    success_count += 1
                else:
                    logger.error("Failed to fetch forecast for point %s (%s)", pt_id, pt["name"])
                    fail_count += 1

    # Preserve stable order matching shanghai_audit_points_100.json
    ordered_points_data = {pt["id"]: points_data[pt["id"]] for pt in points if pt["id"] in points_data}

    # Record quota FIRST (including all failed attempts — the provider bills per
    # request, and failed fetches must not silently escape the hard-cutoff guard),
    # then raise if the whole batch failed.
    record_consumption(
        count=attempt_count,
        purpose=f"Daily audit-point 48h forecast sync ({today_str})",
        metadata={
            "date": today_str,
            "total_points": total_pts,
            "success_count": success_count,
            "fail_count": fail_count,
            "attempt_count": attempt_count
        }
    )

    if success_count == 0:
        raise RuntimeError("All point forecast fetches failed. Check network or credentials.")

    result_payload = {
        "fetch_time": datetime.now(timezone.utc).isoformat(),
        "date": today_str,
        "total_points": total_pts,
        "success_count": success_count,
        "fail_count": fail_count,
        "attempt_count": attempt_count,
        "control_points_count": sum(1 for p in points if p["type"] == "control"),
        "test_points_count": sum(1 for p in points if p["type"] == "test"),
        "points_data": ordered_points_data
    }

    # Save to date-specific file
    with open(today_cache_file, "w", encoding="utf-8") as f:
        json.dump(result_payload, f, ensure_ascii=False, indent=2)

    # Update latest file
    with open(LATEST_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(result_payload, f, ensure_ascii=False, indent=2)

    logger.info("Successfully cached %d points forecast data to %s", success_count, today_cache_file)
    return result_payload
