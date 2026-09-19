"""Weather warning alerts for the landing card, backed by QWeather (和风天气).

The platform already holds server-side QWeather credentials (JWT, see
``qweather_service.QWeatherClient``); this service reuses them so no key ever
reaches the browser. Uses the new-style real-time warning endpoint
``GET /weatheralert/v1/current/{latitude}/{longitude}`` (path parameters,
latitude first, <= 2 decimals); the legacy ``/v7/warning/now`` returns 403 on
dedicated hosts and is scheduled for deprecation. Behaviour stays honest:

- QWeather not configured            -> ``available=False, reason_code='not_configured'``
- provider/network failure           -> ``available=False, reason_code='provider_error'``
- daily QWeather quota exhausted     -> ``available=False, reason_code='quota_exhausted'``
- configured & answered, zero alerts -> ``available=True, alerts=[]`` (truly "无生效预警")

Alerts are cached 10 minutes on a ~55 km grid: meteorological warnings are
issued per administrative city, so nearby visitors share one upstream call.
The v1 payload differs fundamentally from v7 (top-level ``metadata`` +
``alerts``, no ``code``/``warning``), so it is normalized to the platform
contract: title / type_name / level / severity_color / text / pub_time /
start_time / end_time / status.
"""

import logging
import threading
import time
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.services.forecast_quota_manager import can_consume, record_consumption
from app.services.qweather_service import QWeatherClient, QWeatherError

logger = logging.getLogger(__name__)

# v1 预警接口：纬度在前、经度在后，路径参数，最多两位小数
WARNING_PATH_FMT = "/weatheralert/v1/current/{latitude:.2f}/{longitude:.2f}"
COORD_PRECISION = 1  # ~55 km grid, warnings are city-scoped
CACHE_TTL_SECONDS = 600

# color.code（v1 新字段）-> 平台展示色（浅色底上可读的加深值）与中文等级名
_COLOR_DISPLAY = {
    "blue": ("#3b7fd4", "蓝色"),
    "yellow": ("#d9a514", "黄色"),
    "amber": ("#dd8f2b", "橙黄"),
    "orange": ("#d96a26", "橙色"),
    "red": ("#c8442c", "红色"),
    "purple": ("#8a56b0", "紫色"),
    "green": ("#3f9d6d", "绿色"),
    "white": ("#9aa39f", "白色"),
    "gray": ("#8b9490", "灰色"),
    "black": ("#3a3f3d", "黑色"),
}
_SEVERITY_ZH = {"extreme": "极端", "severe": "严重", "moderate": "中等", "minor": "较轻", "unknown": ""}
_MESSAGE_TYPE_ZH = {"alert": "生效中", "update": "更新", "cancel": "已解除"}

_cache: dict[tuple[float, float], tuple[float, dict]] = {}
_cache_lock = threading.Lock()


class _Unavailable(RuntimeError):
    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


def _unavailable(reason_code: str, fetched_at: str) -> dict:
    return {
        "available": False,
        "reason_code": reason_code,
        "update_time": None,
        "source": "QWeather",
        "fetched_at": fetched_at,
        "alerts": [],
    }


def _round(value: float) -> float:
    return round(float(value), COORD_PRECISION)


def _normalize_warning(item: dict) -> dict | None:
    headline = str(item.get("headline") or "").strip()
    if not headline:
        return None
    event = item.get("eventType") if isinstance(item.get("eventType"), dict) else {}
    color = item.get("color") if isinstance(item.get("color"), dict) else {}
    message_type = item.get("messageType") if isinstance(item.get("messageType"), dict) else {}
    color_code = str(color.get("code") or "").strip().lower()
    severity_color, level = _COLOR_DISPLAY.get(color_code, ("#e58d3c", ""))
    if not level:
        level = _SEVERITY_ZH.get(str(item.get("severity") or "").strip().lower(), "")
    type_code = str(message_type.get("code") or "").strip().lower()
    return {
        "title": headline,
        "type_name": str(event.get("name") or "预警").strip(),
        "level": level,
        "severity_color": severity_color,
        "text": str(item.get("description") or "").strip() or headline,
        "pub_time": item.get("issuedTime"),
        "start_time": item.get("effectiveTime") or item.get("onsetTime"),
        "end_time": item.get("expireTime"),
        "status": _MESSAGE_TYPE_ZH.get(type_code, ""),
    }


def get_weather_alerts(longitude: float, latitude: float, transport=None, clock=time.time) -> dict:
    """Return normalized real-time weather warnings for a coordinate (cached)."""
    key = (_round(longitude), _round(latitude))
    now = clock()
    with _cache_lock:
        cached = _cache.get(key)
        if cached and now - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]

    fetched_at = datetime.now(timezone.utc).isoformat()

    client = QWeatherClient(settings, transport=transport)
    try:
        host = client.validate_config()
    except QWeatherError:
        data = _unavailable("not_configured", fetched_at)
        return _store(key, now, data)

    if not can_consume(1):
        return _store(key, now, _unavailable("quota_exhausted", fetched_at))

    try:
        token = client.token()
    except QWeatherError as exc:
        logger.warning("Weather alerts unavailable (token): %s", exc)
        return _store(key, now, _unavailable("not_configured", fetched_at))

    path = WARNING_PATH_FMT.format(latitude=key[1], longitude=key[0])
    try:
        with httpx.Client(timeout=10.0, transport=transport, follow_redirects=False) as http:
            response = http.get(
                f"https://{host}{path}",
                headers={"Authorization": f"Bearer {token}"},
                params={"lang": "zh"},
            )
    except httpx.RequestError as exc:
        logger.warning("Weather alerts request failed: %s", exc)
        return _store(key, now, _unavailable("provider_error", fetched_at))

    try:
        record_consumption(1, "weather_alerts", {"longitude": key[0], "latitude": key[1]})
    except Exception as exc:  # quota bookkeeping must never break the card
        logger.warning("Weather alert quota bookkeeping failed: %s", exc)

    if response.status_code != 200:
        logger.warning("Weather alerts HTTP %s from provider.", response.status_code)
        return _store(key, now, _unavailable("provider_error", fetched_at))

    try:
        payload = response.json()
    except ValueError:
        return _store(key, now, _unavailable("provider_error", fetched_at))

    if not isinstance(payload, dict) or not isinstance(payload.get("alerts"), list):
        logger.warning("Weather alerts response does not match weatheralert/v1/current.")
        return _store(key, now, _unavailable("provider_error", fetched_at))

    alerts = [normalized for item in payload["alerts"] if isinstance(item, dict) and (normalized := _normalize_warning(item))]
    issued_times = [str(a["pub_time"]) for a in alerts if a.get("pub_time")]
    data = {
        "available": True,
        "reason_code": None,
        "update_time": max(issued_times) if issued_times else None,
        "source": "QWeather",
        "fetched_at": fetched_at,
        "alerts": alerts,
    }
    return _store(key, now, data)


def _store(key: tuple[float, float], now: float, data: dict) -> dict:
    with _cache_lock:
        if len(_cache) > 256:
            _cache.clear()
        _cache[key] = (now, data)
    return data
