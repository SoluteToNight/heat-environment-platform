import datetime
import hashlib
import json
import math
import re
import threading
import time
from pathlib import Path

import httpx
import jwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.config import Settings, settings


class QWeatherError(RuntimeError):
    def __init__(self, message: str, retry_after: str | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class QWeatherClient:
    def __init__(self, config: Settings, transport=None, clock=time.time):
        self.config = config
        self.transport = transport
        self.clock = clock
        self._token = ''
        self._expires_at = 0
        self._lock = threading.Lock()

    def validate_config(self):
        host = self.config.QWEATHER_API_HOST.strip().lower()
        if not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+qweatherapi\.com', host):
            raise QWeatherError('QWEATHER_API_HOST must be your dedicated qweatherapi.com hostname without scheme or path.')
        for name in ('QWEATHER_DEVELOPER_ID', 'QWEATHER_PROJECT_ID', 'QWEATHER_KEY_ID'):
            value = getattr(self.config, name)
            if not value or value.startswith('YOUR_') or value != value.strip():
                raise QWeatherError(f'Configure {name} in backend/.env.')
        if not re.fullmatch(r'Q[A-Za-z0-9]{9}', self.config.QWEATHER_DEVELOPER_ID):
            raise QWeatherError('QWEATHER_DEVELOPER_ID must be a 10-character developer ID beginning with Q.')
        return host

    def token(self, refresh=False):
        self.validate_config()
        with self._lock:
            now = int(self.clock())
            if not refresh and self._token and now < self._expires_at - 60:
                return self._token
            key_path = Path(self.config.QWEATHER_PRIVATE_KEY_PATH)
            if not key_path.is_absolute():
                key_path = self.config.BASE_DIR / key_path
            try:
                private_key = load_pem_private_key(key_path.read_bytes(), password=None)
            except (OSError, ValueError, TypeError):
                raise QWeatherError('Cannot read an unencrypted PEM private key at QWEATHER_PRIVATE_KEY_PATH.') from None
            if not isinstance(private_key, Ed25519PrivateKey):
                raise QWeatherError('QWeather requires an Ed25519 private key.')
            issued_at = now - 30
            expires_at = issued_at + self.config.QWEATHER_JWT_TTL_SECONDS
            token = jwt.encode(
                {'iss': self.config.QWEATHER_DEVELOPER_ID, 'sub': self.config.QWEATHER_PROJECT_ID,
                 'iat': issued_at, 'exp': expires_at},
                private_key, algorithm='EdDSA', headers={'kid': self.config.QWEATHER_KEY_ID, 'typ': None},
            )
            self._token = token
            self._expires_at = expires_at
            return token

    def fetch_hourly(self, latitude=None, longitude=None, http_client=None):
        host = self.validate_config()
        latitude = round(self.config.SHANGHAI_CENTER_LAT if latitude is None else latitude, 2)
        longitude = round(self.config.SHANGHAI_CENTER_LON if longitude is None else longitude, 2)
        path = f'/weather/v1/hourly/{latitude:.2f}/{longitude:.2f}'

        def _do_fetch(client):
            for attempt in range(2):
                token = self.token(refresh=attempt == 1)
                try:
                    response = client.get(
                        f'https://{host}{path}',
                        headers={'Authorization': f'Bearer {token}'},
                        params={'hours': self.config.QWEATHER_FORECAST_HOURS, 'localTime': 'false', 'lang': 'zh'},
                    )
                except httpx.RequestError:
                    raise QWeatherError('QWeather connection failed or timed out; no new release was published.') from None
                if response.status_code == 401 and attempt == 0:
                    continue
                if response.status_code != 200:
                    messages = {
                        401: 'JWT authentication failed. Check developer/project/key IDs, matching key pair and system clock.',
                        403: 'Access denied. Check API entitlement and credential restrictions.',
                        429: 'Request limit reached. Wait before retrying.',
                    }
                    raise QWeatherError(
                        f'QWeather HTTP {response.status_code}: ' + messages.get(response.status_code, 'Weather request failed.'),
                        retry_after=response.headers.get('Retry-After'),
                    )
                try:
                    payload = response.json()
                except ValueError:
                    raise QWeatherError('QWeather returned invalid JSON.') from None
                return normalize_hourly(payload, latitude, longitude, path)

        if http_client is not None:
            return _do_fetch(http_client)
        with httpx.Client(timeout=self.config.WEATHER_REQUEST_TIMEOUT_SECONDS, transport=self.transport, follow_redirects=False) as client:
            return _do_fetch(client)


def numeric(value, field, minimum=None, maximum=None):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise QWeatherError(f'Invalid QWeather numeric field: {field}.')
    if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        raise QWeatherError(f'Out-of-range QWeather field: {field}.')
    return float(value)


def measurement(value, field, unit):
    if value is None:
        return None
    if not isinstance(value, dict) or value.get('unit') != unit:
        raise QWeatherError(f'Unexpected QWeather unit for {field}; expected {unit}.')
    return numeric(value.get('value'), field, minimum=0 if field == 'wind.speed' else None)


def normalize_hourly(payload, latitude, longitude, endpoint):
    if not isinstance(payload, dict) or not isinstance(payload.get('hours'), list) or not payload['hours']:
        raise QWeatherError('QWeather hourly response is empty or does not match weather/v1/hourly.')
    metadata = payload.get('metadata') or {}
    if not isinstance(metadata, dict) or not isinstance(metadata.get('attributions', []), list):
        raise QWeatherError('QWeather metadata is invalid.')
    hourly = {name: [] for name in ('time', 'temperature_2m', 'relative_humidity_2m', 'wind_speed_10m', 'wind_direction_10m', 'dew_point')}
    previous_time = None
    for hour in payload['hours']:
        try:
            forecast_time = datetime.datetime.fromisoformat(hour['forecastTime'].replace('Z', '+00:00'))
            if forecast_time.tzinfo is None:
                raise ValueError()
            forecast_time = forecast_time.astimezone(datetime.timezone.utc)
            if previous_time is not None and forecast_time <= previous_time:
                raise ValueError()
            previous_time = forecast_time
            wind = hour.get('wind') or {}
            direction = wind.get('direction') or {}
            humidity = numeric(hour.get('humidity'), 'humidity', 0, 1)
            hourly['time'].append(forecast_time.isoformat())
            hourly['temperature_2m'].append(measurement(hour.get('temperature'), 'temperature', '°C'))
            hourly['dew_point'].append(measurement(hour.get('dewPoint'), 'dewPoint', '°C'))
            hourly['relative_humidity_2m'].append(None if humidity is None else humidity * 100)
            hourly['wind_speed_10m'].append(measurement(wind.get('speed'), 'wind.speed', 'm/s'))
            wind_dir = numeric(direction.get('degree'), 'wind.direction', 0, 360)
            hourly['wind_direction_10m'].append(None if wind_dir is None else wind_dir % 360)
        except (KeyError, TypeError, ValueError, AttributeError):
            raise QWeatherError('QWeather hourly structure or timezone/order is invalid.') from None
    if not any(value is not None for name, values in hourly.items() if name != 'time' for value in values):
        raise QWeatherError('QWeather returned no usable weather values.')
    try:
        source_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, TypeError):
        raise QWeatherError('QWeather source payload contains invalid JSON values.') from None
    return {
        'hourly': hourly,
        'hourly_units': {'temperature_2m': '°C', 'relative_humidity_2m': '%', 'wind_speed_10m': 'm/s', 'wind_direction_10m': '°'},
        'is_fallback': False,
        'latitude': latitude, 'longitude': longitude,
        'provider_meta': {
            'provider': 'qweather', 'endpoint': endpoint, 'source_payload': payload,
            'source_sha256': hashlib.sha256(source_bytes).hexdigest(),
            'attributions': metadata.get('attributions', []),
            'spatial_support': 'One requested forecast location; not a citywide raster or street-level observation.',
            'receiver_height': 'Not specified by the hourly API; legacy storage column suffixes do not establish measurement height.',
            'temporal_support': 'hourly_forecast',
        },
    }


qweather_client = QWeatherClient(settings)
