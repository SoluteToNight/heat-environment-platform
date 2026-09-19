"""Offline unit tests for the landing-card weather services (no DB, no network)."""

import httpx
import pytest

from app.services import weather_alert_service, weather_point_service
from app.services.qweather_service import QWeatherError
from app.services.utci_service import calculate_tmrt, calculate_utci


@pytest.fixture(autouse=True)
def _clear_service_caches():
    weather_point_service._cache.clear()
    weather_alert_service._cache.clear()
    yield
    weather_point_service._cache.clear()
    weather_alert_service._cache.clear()


def _open_meteo_payload() -> dict:
    return {
        "timezone": "Asia/Shanghai",
        "utc_offset_seconds": 28800,
        "current": {"time": "2026-09-19T14:30", "temperature_2m": 32.5, "relative_humidity_2m": 65,
                    "wind_speed_10m": 3.2, "shortwave_radiation": 650.0},
        "hourly": {
            "time": ["2026-09-19T12:00", "2026-09-19T13:00", "2026-09-19T14:00", "2026-09-19T15:00", "2026-09-19T16:00"],
            "temperature_2m": [30.0, 31.0, 32.5, 31.8, 30.9],
            "relative_humidity_2m": [70, 68, 65, 66, 70],
            "wind_speed_10m": [3.0, 3.1, 3.2, 3.0, 2.8],
            "shortwave_radiation": [400.0, 620.0, 650.0, 500.0, 200.0],
        },
    }


def _point_transport(counter: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        counter["calls"] += 1
        assert request.url.host == "api.open-meteo.com"
        assert request.url.params["wind_speed_unit"] == "ms"
        return httpx.Response(200, json=_open_meteo_payload())
    return httpx.MockTransport(handler)


def test_weather_point_computes_utci_with_backend_model():
    data = weather_point_service.get_weather_point_forecast(
        longitude=121.4737, latitude=31.2304,
        transport=_point_transport({"calls": 0}), clock=lambda: 1000.0,
    )
    # “现在”锚定到查询坐标当地当前小时
    assert data["now_index"] == 2
    assert data["current"]["time"] == "2026-09-19T14:00"
    # UTCI 必须与 utci_service（pythermalcomfort）直算结果一致：同一套算法口径
    tmrt = calculate_tmrt(ta_c=32.5, solar_rad_w_m2=650.0)
    expected_sun, _ = calculate_utci(ta_c=32.5, rh_percent=65, wind_speed_m_s=3.2, tmrt_c=tmrt)
    expected_shade, _ = calculate_utci(ta_c=32.5, rh_percent=65, wind_speed_m_s=3.2, tmrt_c=32.5)
    assert data["current"]["utci_c"] == round(expected_sun, 1)
    assert data["current"]["utci_shade_c"] == round(expected_shade, 1)
    assert data["current"]["stress"]["zh"] in {"无热应激", "中度热应激", "强热应激", "很强热应激", "极强热应激"}
    assert data["peak"]["utci_c"] == max(r["utci_c"] for r in data["hourly"])
    assert len(data["hourly"]) == 5
    assert data["source"]["provider"] == "Open-Meteo"


def test_weather_point_rounds_coordinates_and_caches():
    counter = {"calls": 0}
    transport = _point_transport(counter)
    first = weather_point_service.get_weather_point_forecast(
        longitude=121.4737, latitude=31.2304, transport=transport, clock=lambda: 1000.0,
    )
    # 坐标取整到 ~1.1 km 网格，随后 15 分钟内的请求命中缓存，不再消耗服务商调用
    second = weather_point_service.get_weather_point_forecast(
        longitude=121.4740, latitude=31.2310, transport=transport, clock=lambda: 1400.0,
    )
    assert first["location"] == {"longitude": 121.47, "latitude": 31.23, "grid_rounded": True}
    assert second is first
    assert counter["calls"] == 1
    weather_point_service.get_weather_point_forecast(
        longitude=121.47, latitude=31.23, transport=transport, clock=lambda: 1000.0 + 3600,
    )
    assert counter["calls"] == 2


def test_weather_point_raises_honest_error_on_provider_failure():
    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": True})
    with pytest.raises(weather_point_service.WeatherFetchError):
        weather_point_service.get_weather_point_forecast(
            longitude=121.47, latitude=31.23, transport=httpx.MockTransport(broken), clock=lambda: 5000.0,
        )


class _StubQWeather:
    """Stands in for QWeatherClient without touching real credentials."""

    instances: list["_StubQWeather"] = []

    def __init__(self, config=None, transport=None, clock=None):
        self.transport = transport
        self.requests: list[httpx.Request] = []
        _StubQWeather.instances.append(self)

    def validate_config(self):
        return "api.qweatherapi.com"

    def token(self, refresh=False):
        return "stub-jwt"


def test_weather_alerts_normalizes_provider_warnings(monkeypatch):
    monkeypatch.setattr(weather_alert_service, "QWeatherClient", _StubQWeather)
    monkeypatch.setattr(weather_alert_service, "can_consume", lambda n: True)
    monkeypatch.setattr(weather_alert_service, "record_consumption", lambda *a, **k: {})

    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        assert request.headers["Authorization"] == "Bearer stub-jwt"
        assert request.url.params["lang"] == "zh"
        assert "location" not in request.url.params  # v1 用路径参数，不再用 location 查询参数
        return httpx.Response(200, json={
            "metadata": {"tag": "2026-09-19T13:40+08:00", "zeroResult": False, "attributions": []},
            "alerts": [
                {"id": "w1", "senderName": "上海中心气象台", "issuedTime": "2026-09-19T00:45+00:00",
                 "messageType": {"code": "alert", "supersedes": []},
                 "eventType": {"name": "高温", "code": "high-temperature"},
                 "urgency": "expected", "severity": "severe", "certainty": "likely", "icon": "1001",
                 "color": {"code": "orange", "red": 255, "green": 106, "blue": 77, "alpha": 1},
                 "effectiveTime": "2026-09-19T01:00+00:00", "onsetTime": None,
                 "expireTime": "2026-09-19T10:00+00:00",
                 "headline": "上海中心气象台发布高温橙色预警",
                 "description": "受副热带高压影响，预计今天全市大部分地区最高气温将达37℃以上。",
                 "criteria": "连续三天 35℃ 以上", "responseTypes": [], "instruction": "午后减少户外活动。"},
                {"eventType": {"name": "高温"}},  # 缺少 headline 应被过滤
                "junk",  # 非对象元素应被过滤
            ],
        })

    data = weather_alert_service.get_weather_alerts(
        longitude=121.4737, latitude=31.2304, transport=httpx.MockTransport(handler), clock=lambda: 1000.0,
    )
    assert data["available"] is True
    assert data["update_time"] == "2026-09-19T00:45+00:00"  # v1 无顶层 updateTime，取预警内最晚 issuedTime
    assert [a["type_name"] for a in data["alerts"]] == ["高温"]
    assert data["alerts"][0]["title"] == "上海中心气象台发布高温橙色预警"
    assert data["alerts"][0]["level"] == "橙色"  # color.code=orange → 中文等级
    assert data["alerts"][0]["severity_color"] == "#d96a26"
    assert data["alerts"][0]["status"] == "生效中"
    assert data["alerts"][0]["start_time"] == "2026-09-19T01:00+00:00"
    assert data["alerts"][0]["end_time"] == "2026-09-19T10:00+00:00"
    assert "37℃" in data["alerts"][0]["text"]
    # 纬度在前、经度在后，坐标经 0.1° 缓存网格取整后保留两位小数
    assert seen["path"] == weather_alert_service.WARNING_PATH_FMT.format(latitude=31.20, longitude=121.50)


def test_weather_alerts_degrades_honestly_when_unconfigured(monkeypatch):
    class Unconfigured(_StubQWeather):
        def validate_config(self):
            raise QWeatherError("not configured")

    monkeypatch.setattr(weather_alert_service, "QWeatherClient", Unconfigured)
    data = weather_alert_service.get_weather_alerts(
        longitude=121.47, latitude=31.23, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
        clock=lambda: 1000.0,
    )
    assert data == {**data, "available": False, "reason_code": "not_configured", "alerts": []}


def test_weather_alerts_respects_quota_guard(monkeypatch):
    monkeypatch.setattr(weather_alert_service, "QWeatherClient", _StubQWeather)
    monkeypatch.setattr(weather_alert_service, "can_consume", lambda n: False)
    data = weather_alert_service.get_weather_alerts(
        longitude=121.47, latitude=31.23, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
        clock=lambda: 1000.0,
    )
    assert data["available"] is False
    assert data["reason_code"] == "quota_exhausted"
