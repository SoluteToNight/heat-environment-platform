import copy
import datetime
from unittest.mock import MagicMock

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.config import Settings
from app.qweather_setup import generate_keys
from app.services.qweather_service import QWeatherClient, QWeatherError, normalize_hourly


@pytest.fixture
def credentials(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    key_path = tmp_path / 'private.pem'
    key_path.write_bytes(private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    config = Settings(_env_file=None, QWEATHER_API_HOST='testing.qweatherapi.com', QWEATHER_DEVELOPER_ID='Q12345ABCD', QWEATHER_PROJECT_ID='project', QWEATHER_KEY_ID='credential', QWEATHER_PRIVATE_KEY_PATH=str(key_path))
    return config, private_key


@pytest.fixture
def payload():
    return {
        'metadata': {'tag': 'sample', 'attributions': ['https://developer.qweather.com/attribution.html']},
        'hours': [
            {'forecastTime': '2026-09-17T08:00+08:00', 'temperature': {'value': 0, 'unit': '°C'}, 'humidity': 0.76,
             'wind': {'speed': {'value': 3.6, 'unit': 'm/s'}, 'direction': {'degree': 0}}},
            {'forecastTime': '2026-09-17T09:00+08:00', 'temperature': None, 'humidity': None, 'wind': None},
        ],
    }


def normalize(payload):
    return normalize_hourly(payload, 31.23, 121.47, '/weather/v1/hourly/31.23/121.47')


def test_signed_claims_and_refresh(credentials):
    config, private_key = credentials
    clock = [2000000000]
    client = QWeatherClient(config, clock=lambda: clock[0])
    first = client.token()
    header = jwt.get_unverified_header(first)
    claims = jwt.decode(first, private_key.public_key(), algorithms=['EdDSA'], options={'verify_iat': False, 'verify_exp': False})
    assert header == {'alg': 'EdDSA', 'kid': 'credential'}
    assert claims == {'iss': 'Q12345ABCD', 'sub': 'project', 'iat': clock[0] - 30, 'exp': clock[0] - 30 + 900}
    clock[0] += 100
    assert client.token() == first
    clock[0] += 720
    assert client.token() != first


@pytest.mark.parametrize('host', ['https://testing.qweatherapi.com', 'testing.qweatherapi.com/route', 'testing.qweatherapi.com.evil.test', '127.0.0.1', 'user@testing.qweatherapi.com'])
def test_rejects_unsafe_host(credentials, host):
    config, _ = credentials
    config.QWEATHER_API_HOST = host
    with pytest.raises(QWeatherError, match='hostname'):
        QWeatherClient(config).token()


def test_missing_key_is_safe_error(credentials):
    config, _ = credentials
    config.QWEATHER_PRIVATE_KEY_PATH = 'nonexistent/private.pem'
    with pytest.raises(QWeatherError, match='Cannot read'):
        QWeatherClient(config).token()


def test_request_and_unit_mapping(credentials, payload):
    config, private_key = credentials
    requests = []
    def handler(request):
        requests.append(request)
        token = request.headers['Authorization'].removeprefix('Bearer ')
        jwt.decode(token, private_key.public_key(), algorithms=['EdDSA'], issuer=config.QWEATHER_DEVELOPER_ID, subject=config.QWEATHER_PROJECT_ID)
        return httpx.Response(200, json=payload)
    result = QWeatherClient(config, transport=httpx.MockTransport(handler)).fetch_hourly()
    assert requests[0].url.path == '/weather/v1/hourly/31.23/121.47'
    assert dict(requests[0].url.params) == {'hours': '48', 'localTime': 'false', 'lang': 'zh'}
    assert result['hourly']['time'][0] == '2026-09-17T00:00:00+00:00'
    assert result['hourly']['temperature_2m'] == [0, None]
    assert result['hourly']['relative_humidity_2m'] == [76, None]
    assert result['hourly']['wind_speed_10m'] == [3.6, None]
    assert result['hourly']['wind_direction_10m'] == [0, None]
    assert 'shortwave_radiation' not in result['hourly']
    assert result['provider_meta']['source_payload'] == payload
    assert len(result['provider_meta']['source_sha256']) == 64


@pytest.mark.parametrize('status,expected_calls', [(401, 2), (403, 1), (429, 1), (500, 1), (302, 1)])
def test_errors_never_fall_back_or_follow_redirects(credentials, status, expected_calls):
    config, _ = credentials
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={'Retry-After': '120', 'Location': 'https://other.example/'}, json={'message': 'untrusted upstream body'})
    with pytest.raises(QWeatherError) as caught:
        QWeatherClient(config, transport=httpx.MockTransport(handler)).fetch_hourly()
    assert len(calls) == expected_calls
    assert caught.value.retry_after == '120'
    assert 'untrusted' not in str(caught.value)
    assert 'Bearer' not in str(caught.value)


def test_auth_retry_can_recover(credentials, payload):
    config, _ = credentials
    responses = iter([httpx.Response(401), httpx.Response(200, json=payload)])
    client = QWeatherClient(config, transport=httpx.MockTransport(lambda request: next(responses)))
    assert client.fetch_hourly()['is_fallback'] is False


def test_timeout_has_no_secret_or_synthetic_result(credentials):
    config, _ = credentials
    def handler(request):
        raise httpx.ReadTimeout('sensitive request detail', request=request)
    with pytest.raises(QWeatherError, match='timed out') as caught:
        QWeatherClient(config, transport=httpx.MockTransport(handler)).fetch_hourly()
    assert 'sensitive' not in str(caught.value)


@pytest.mark.parametrize('change', ['bad_humidity', 'unit', 'duplicate', 'naive', 'empty', 'infinite'])
def test_invalid_provider_data_is_rejected(payload, change):
    modified = copy.deepcopy(payload)
    if change == 'bad_humidity': modified['hours'][0]['humidity'] = 76
    if change == 'unit': modified['hours'][0]['wind']['speed']['unit'] = 'km/h'
    if change == 'duplicate': modified['hours'][1]['forecastTime'] = modified['hours'][0]['forecastTime']
    if change == 'naive': modified['hours'][0]['forecastTime'] = '2026-09-17T08:00'
    if change == 'empty': modified['hours'] = []
    if change == 'infinite': modified['hours'][0]['temperature']['value'] = float('inf')
    with pytest.raises(QWeatherError):
        normalize(modified)


def test_publish_preserves_origin_and_missing_radiation(monkeypatch, payload):
    from app.services import qweather_service, weather_service
    database = MagicMock()
    monkeypatch.setattr(qweather_service.qweather_client, 'fetch_hourly', lambda: normalize(payload))
    release = weather_service.sync_weather_release(database, product_id='qweather', force=True)
    assert release.product_id == 'qweather'
    assert release.raw_meta['latitude'] == 31.23
    assert release.raw_meta['source_payload'] == payload
    records = database.bulk_save_objects.call_args.args[0]
    assert len(records) == 2
    assert records[0].lon == 121.47
    assert records[0].shortwave_radiation is None
    assert records[0].temperature_2m == 0
    database.commit.assert_called_once()


def test_failed_fetch_does_not_publish(monkeypatch):
    from app.services import qweather_service, weather_service
    database = MagicMock()
    def fail(): raise QWeatherError('JWT authentication failed')
    monkeypatch.setattr(qweather_service.qweather_client, 'fetch_hourly', fail)
    with pytest.raises(QWeatherError):
        weather_service.sync_weather_release(database, product_id='qweather', force=True)
    database.add.assert_not_called()
    database.commit.assert_not_called()


def test_catalog_uses_selected_provider_and_capabilities(monkeypatch):
    from app.services import env_service
    monkeypatch.setattr(env_service.settings, 'WEATHER_PROVIDER', 'qweather')
    catalogs = env_service.get_environment_catalog('scene_shanghai')
    assert [catalog.product_id for catalog in catalogs] == ['qweather']
    variables = {variable.code: variable for variable in catalogs[0].variables}
    assert variables['wind_speed'].name == '风速'
    assert variables['air_temperature'].availability == 'available'
    assert variables['shortwave_radiation'].availability == 'unsupported'
    assert variables['net_shortwave_background'].availability == 'unsupported'


def test_latest_selection_excludes_old_provider(monkeypatch, payload):
    from app.db.models import EnvRelease, WeatherRecord, utc_now
    from app.schemas.environment import CreateViewRequest
    from app.services import env_service
    database = MagicMock()
    now = utc_now()
    release = EnvRelease(id='qweather-release', scene_id='scene_shanghai', product_id='qweather', computed_at=now, raw_meta=normalize(payload)['provider_meta'])
    record = WeatherRecord(target_time=now, temperature_2m=25)
    release_query = MagicMock()
    release_query.filter.return_value.order_by.return_value.first.return_value = release
    record_query = MagicMock()
    record_query.filter.return_value.order_by.return_value.first.return_value = record
    database.query.side_effect = lambda model: release_query if model is EnvRelease else record_query
    monkeypatch.setattr(env_service.settings, 'WEATHER_PROVIDER', 'qweather')
    result = env_service.create_fixed_view(database, CreateViewRequest(variables=['air_temperature', 'shortwave_radiation'], time_selection={'kind': 'now'}))
    clauses = release_query.filter.call_args.args
    assert any('product_id' in str(clause) and clause.right.value == 'qweather' for clause in clauses)
    assert result.variables[0].release_id == 'qweather-release'
    assert result.variables[1].availability == 'unsupported'


def test_key_generation_never_overwrites(tmp_path):
    generate_keys(tmp_path)
    before = (tmp_path / 'qweather-private.pem').read_bytes()
    with pytest.raises(QWeatherError, match='already exist'):
        generate_keys(tmp_path)
    assert (tmp_path / 'qweather-private.pem').read_bytes() == before


def test_historical_request_cannot_use_current_forecast(monkeypatch):
    from fastapi import HTTPException
    from app.db.models import EnvRelease, utc_now
    from app.schemas.environment import CreateViewRequest
    from app.services import env_service
    database = MagicMock()
    now = utc_now()
    release = EnvRelease(id='recent', scene_id='scene_shanghai', product_id='qweather', computed_at=now, time_start=now, time_end=now + datetime.timedelta(hours=48))
    database.query.return_value.filter.return_value.order_by.return_value.first.return_value = release
    monkeypatch.setattr(env_service.settings, 'WEATHER_PROVIDER', 'qweather')
    with pytest.raises(HTTPException) as caught:
        env_service.create_fixed_view(database, CreateViewRequest(variables=['air_temperature'], time_selection={'kind': 'at', 'time': '2024-06-01T00:00:00Z'}))
    assert caught.value.status_code == 422
    database.add.assert_not_called()


def test_missing_release_returns_service_error_without_other_provider(monkeypatch):
    from fastapi import HTTPException
    from app.schemas.environment import CreateViewRequest
    from app.services import env_service
    database = MagicMock()
    database.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    def fail(*args, **kwargs): raise QWeatherError('Request limit reached', retry_after='120')
    monkeypatch.setattr(env_service, 'sync_weather_release', fail)
    monkeypatch.setattr(env_service.settings, 'WEATHER_PROVIDER', 'qweather')
    with pytest.raises(HTTPException) as caught:
        env_service.create_fixed_view(database, CreateViewRequest(variables=['air_temperature'], time_selection={'kind': 'now'}))
    assert caught.value.status_code == 503
    assert caught.value.headers == {'Retry-After': '120'}
    database.add.assert_not_called()


def test_wrong_key_algorithm_is_rejected(credentials, tmp_path):
    from cryptography.hazmat.primitives.asymmetric import ec
    config, _ = credentials
    private_key = ec.generate_private_key(ec.SECP256R1())
    key_path = tmp_path / 'wrong-key.pem'
    key_path.write_bytes(private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    config.QWEATHER_PRIVATE_KEY_PATH = str(key_path)
    with pytest.raises(QWeatherError, match='Ed25519'):
        QWeatherClient(config).token()
