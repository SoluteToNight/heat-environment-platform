"""Hourly Weather Forecast Fetch Service for Shanghai 100 Control & Test Points.

Fetches rolling 48-hour hourly weather forecasts (temperature, humidity, wind, dew point)
for 90 Control Points + 10 Independent Test Points, with built-in daily caching,
rate limiting, and strict quota guard protection.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

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
    points_data = {}
    success_count = 0
    fail_count = 0

    for idx, pt in enumerate(points, 1):
        pt_id = pt["id"]
        lat = pt["lat"]
        lon = pt["lon"]
        hourly_data = None

        # Retry up to 2 attempts for resilience
        for attempt in range(2):
            try:
                res = client.fetch_hourly(latitude=lat, longitude=lon)
                hourly_data = res.get("hourly")
                break
            except Exception as exc:
                logger.warning("Point %s (Attempt %d) failed: %s", pt_id, attempt + 1, exc)
                time.sleep(0.3)

        if hourly_data:
            points_data[pt_id] = {
                "id": pt_id,
                "name": pt["name"],
                "district": pt["district"],
                "type": pt["type"],
                "lon": lon,
                "lat": lat,
                "tag": pt.get("tag", ""),
                "hourly": hourly_data
            }
            success_count += 1
        else:
            logger.error("Failed to fetch forecast for point %s (%s)", pt_id, pt["name"])
            fail_count += 1

        # Rate-limiting pause between requests (50ms)
        time.sleep(0.05)

    if success_count == 0:
        raise RuntimeError("All point forecast fetches failed. Check network or credentials.")

    # Record API consumption
    record_consumption(
        count=success_count,
        purpose=f"Daily 100-point 48h forecast sync ({today_str})",
        metadata={
            "date": today_str,
            "success_count": success_count,
            "fail_count": fail_count
        }
    )

    result_payload = {
        "fetch_time": datetime.now(timezone.utc).isoformat(),
        "date": today_str,
        "total_points": total_pts,
        "success_count": success_count,
        "fail_count": fail_count,
        "control_points_count": sum(1 for p in points if p["type"] == "control"),
        "test_points_count": sum(1 for p in points if p["type"] == "test"),
        "points_data": points_data
    }

    # Save to date-specific file
    with open(today_cache_file, "w", encoding="utf-8") as f:
        json.dump(result_payload, f, ensure_ascii=False, indent=2)

    # Update latest file
    with open(LATEST_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(result_payload, f, ensure_ascii=False, indent=2)

    logger.info("Successfully cached %d points forecast data to %s", success_count, today_cache_file)
    return result_payload
