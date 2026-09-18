import copy
import datetime
import io
import json
import math
import struct

import numpy as np
import pytest
from PIL import Image
from shapely.geometry import box

from app.services import spatial_service as spatial
from app.services.spatial_math import interpolate, wind_components, wind_from_components, ray_visibility, sky_factor, local_shortwave, solar_position
from app.services.radiation_service import decode_tile, downscale_components
from app.routers.spatial import series, export


def test_linear_field_and_no_extrapolation():
    points = np.array([[0, 0], [2, 0], [0, 2]])
    result = interpolate(points, [0, 4, 6], [[.5, .5], [3, 3]])
    assert result[0] == pytest.approx(2.5)
    assert np.isnan(result[1])
    assert np.isnan(interpolate(points, [0, np.nan, 6], [[.5, .5]])[0])
    assert interpolate(points, [0, np.nan, 6], [[0, 0]])[0] == 0


def test_wind_wrap_and_calm():
    east, north = wind_components([5, 5], [359, 1])
    speed, direction = wind_from_components(np.mean(east), np.mean(north))
    assert speed == pytest.approx(5, abs=.001)
    assert min(abs(direction), abs(direction - 360)) < .001
    east, north = wind_components(0, np.nan)
    speed, direction = wind_from_components(east, north)
    assert speed == 0 and np.isnan(direction)


def test_radiation_geometry_and_components():
    obstacle = box(-5, 10, 5, 20)
    assert ray_visibility(0, 0, 1.1, 0, math.pi / 4, [(obstacle, 30)], 100) == 0
    assert ray_visibility(0, 0, 1.1, math.pi, math.pi / 4, [(obstacle, 30)], 100) == 1
    assert np.isnan(ray_visibility(0, 0, 1.1, 0, math.pi / 4, [(obstacle, None)], 100))
    assert ray_visibility(0, 0, 1.1, 0, -.1, [], 100) == 0
    assert sky_factor(0, 0, 1.1, [], 100) == 1
    assert local_shortwave(800, 100, math.pi / 6, 1, 1) == pytest.approx(500)
    assert local_shortwave(800, 100, math.pi / 6, 0, .5) == 50
    assert local_shortwave(800, 100, .5, None, 1) is None
    with pytest.raises(ValueError):
        downscale_components([], 100, 20, 'net_shortwave', 'instant')
    with pytest.raises(ValueError):
        downscale_components([], 100, 20, 'dni_dhi', 'interval_mean')
    with pytest.raises(ValueError):
        solar_position(121, 31, datetime.datetime(2026, 9, 17))


def test_decoder_disallows_old_header_window():
    pixels = np.zeros((265, 257, 4), dtype=np.uint8)
    pixels[:, :, 3] = 255
    raw = pixels.ravel()
    for index, value in enumerate(struct.pack('<7f', 0, 1000, 0, 0, 0, 0, 0)):
        offset = 4 * 257 * 4 + 16 + index * 32
        raw[offset:offset + 3] = [(value >> 6) * 64, ((value >> 2) & 15) * 16, (value & 3) * 64]
    stream = io.BytesIO()
    Image.fromarray(pixels).save(stream, format='PNG')
    profile = dict(verified=True, evidence='synthetic encoding fixture only', width=257, height=265, header_offset=4128, header_stride=32, data_x=0, data_y=0, data_width=256, data_height=256, nodata_codes=[], quantity='net_shortwave', unit='W/m²', valid_time='2026-09-17T04:00:00Z', temporal_support='instant', z=4, x=13, y=6)
    with pytest.raises(ValueError, match='overlaps'):
        decode_tile(stream.getvalue(), profile)
    profile['data_y'] = 8
    values, metadata = decode_tile(stream.getvalue(), profile)
    assert values.shape == (256, 256)
    assert metadata['max'] == 1000


@pytest.fixture
def publication(tmp_path, monkeypatch):
    monkeypatch.setattr(spatial.settings, 'SPATIAL_STORAGE_DIR', tmp_path / 'publications')
    boundary = tmp_path / 'boundary.geojson'
    boundary.write_text(json.dumps({'type': 'Polygon', 'coordinates': [[[121, 30], [122, 30], [122, 32], [121, 32], [121, 30]]]}))
    monkeypatch.setattr(spatial, 'boundary_path', lambda: boundary)
    calls = []
    def fetch(latitude, longitude):
        calls.append((longitude, latitude))
        return {'hourly': {'time': ['2026-09-17T04:00:00+00:00', '2026-09-17T05:00:00+00:00'], 'temperature_2m': [30, 32], 'relative_humidity_2m': [60, 65], 'wind_speed_10m': [3, 4], 'wind_direction_10m': [359, 1], 'dew_point': [20, None]}, 'provider_meta': {'attributions': ['QWeather test fixture']}}
    monkeypatch.setattr(spatial.qweather_client, 'fetch_hourly', fetch)
    return spatial.sampling_plan(121.47, 31.23), calls


def test_shared_cache_snapshot_raster_series_and_export(publication):
    plan, calls = publication
    manifest = spatial.publish_weather(plan)
    second = spatial.publish_weather(plan)
    assert len(calls) == len(plan['points'])
    assert second['actual_calls'] == 0
    view = spatial.create_view({'kind': 'at', 'time': '2026-09-17T12:00:00+08:00'}, ['air_temperature', 'dew_point'])
    assert view['items'][0]['resolved_time'] == '2026-09-17T04:00:00Z'
    point = spatial.point_result(view['view_id'], 121.47, 31.23)
    assert point['items'][0]['value'] == pytest.approx(30)
    readings = series(view['view_id'], 121.47, 31.23)['data']
    assert readings['points'][0]['value'] == point['items'][0]['value']
    assert export(view['view_id'], 121.47, 31.23).body.startswith(b'\xef\xbb\xbf')
    assert spatial.point_result(view['view_id'], 120, 30)['items'][0]['value'] is None
    raster = Image.open(io.BytesIO(spatial.raster_png(manifest['run_id'], 'air_temperature', 0, 16)))
    assert raster.mode == 'RGBA' and raster.size == (16, 16)
    assert np.asarray(raster)[:, :, 3].max() > 0
    latest = spatial.read_release()[1]['run_id']
    with pytest.raises(ValueError):
        spatial.publish_weather({**plan, 'points': [[121.47, 31.23]]}, force=True)
    assert spatial.read_release()[1]['run_id'] == latest
    assert spatial.read_view(view['view_id'])['items'][0]['release_id'] == second['run_id']
    old = spatial.create_view({'kind': 'at', 'time': '2025-01-01T00:00:00Z'}, ['air_temperature'])
    assert old['items'][0]['assets'] == []
    assert spatial.point_result(old['view_id'], 121.47, 31.23)['items'][0]['value'] is None
