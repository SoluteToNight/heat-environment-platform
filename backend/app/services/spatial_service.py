import datetime
import hashlib
import io
import json
import os
import re
import uuid
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.interpolate import RegularGridInterpolator
from scipy.spatial import cKDTree
from shapely import contains_xy
from shapely.geometry import shape
from shapely.ops import unary_union

from app.config import settings
from app.services.qweather_service import qweather_client, QWeatherError
from app.services.spatial_math import PROJECT, EXCHANGE, interpolate, wind_components, wind_from_components


VARIABLES = {
    'utci': ('通用热气候指数 (UTCI)', '°C', 10, 45, ['#313695', '#4575b4', '#74add1', '#abd9e9', '#fee090', '#fdae61', '#f46d43', '#d73027']),
    'air_temperature': ('气温', '°C', 0, 40, ['#2c7bb6', '#74add1', '#abd9e9', '#ffffbf', '#fdae61', '#f46d43', '#d7191c']),
    'relative_humidity': ('相对湿度', '%', 0, 100, ['#f7fcf5', '#caeac3', '#7bcbc4', '#3690c0', '#023858']),
    'wind_speed': ('风速', 'm/s', 0, 15, ['#ffffcc', '#a1dab4', '#41b6c4', '#2c7fb8', '#253494']),
    'dew_point': ('露点', '°C', -10, 30, ['#e7eed9', '#b4d2bc', '#79afa5', '#4d7c8a']),
    'solar_radiation': ('太阳下行辐射', 'W/m²', 0, 1000, ['#f4edc9', '#eed496', '#d7a063', '#ac664c']),
    'net_shortwave_background': ('区域净短波', 'W/m²', 0, 1200, ['#f4edc9', '#eed496', '#d7a063', '#ac664c']),
    'local_downwelling_shortwave': ('局地下行短波估计（未含反射）', 'W/m²', 0, 1200, ['#f4edc9', '#eed496', '#d7a063', '#ac664c']),
    'sun_visibility': ('太阳可见系数（建筑情景）', '1', 0, 1, ['#465b71', '#f3d59a']),
    'sky_factor': ('天空因子（建筑情景）', '1', 0, 1, ['#465b71', '#aed7da']),
}
WEATHER_VARIABLES = ('air_temperature', 'relative_humidity', 'wind_east', 'wind_north', 'dew_point')


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def utc_text(value):
    return value.astimezone(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def boundary_path():
    return settings.BASE_DIR.parent.parent / 'data/osm/shanghai/shanghai_boundary.geojson'


def load_boundary(path=None):
    source = json.loads(Path(path or boundary_path()).read_text(encoding='utf-8-sig'))
    if source['type'] == 'FeatureCollection':
        return unary_union([shape(feature['geometry']) for feature in source['features']])
    return shape(source.get('geometry', source))


def sampling_plan(longitude, latitude, spacing=1000, side=3):
    if side < 2 or side > 20 or spacing < 500:
        raise ValueError('Use side 2–20 and spacing >= 500 metres.')
    center_east, center_north = PROJECT.transform(longitude, latitude)
    points = []
    for row in range(side):
        for column in range(side):
            east = center_east + (column - (side - 1) / 2) * spacing
            north = center_north + (row - (side - 1) / 2) * spacing
            lon, lat = EXCHANGE.transform(east, north)
            point = (round(lon, 2), round(lat, 2))
            if point not in points:
                points.append(point)
    if len(points) < 4 or len(points) > settings.SPATIAL_MAX_POINTS:
        raise ValueError(f'Actual distinct locations {len(points)} outside 4–{settings.SPATIAL_MAX_POINTS}.')
    boundary = load_boundary()
    if not boundary.covers(shape({'type': 'Point', 'coordinates': [longitude, latitude]})):
        raise ValueError('Pilot centre is outside the configured Shanghai boundary.')
    return {'points': points, 'requested_spacing_m': spacing, 'side': side, 'planned_calls': len(points), 'forecast_hours': settings.QWEATHER_FORECAST_HOURS, 'crs': 'EPSG:32651', 'request_crs': 'EPSG:4326', 'coordinate_rounding': 2}


def fetch_cached(longitude, latitude, force=False):
    cache = settings.SPATIAL_STORAGE_DIR / 'cache'
    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(f'{settings.QWEATHER_API_HOST}|hourly-v1|{latitude:.2f}|{longitude:.2f}|{settings.QWEATHER_FORECAST_HOURS}'.encode()).hexdigest()
    path = cache / f'{key}.json'
    if path.exists() and not force:
        saved = json.loads(path.read_text(encoding='utf-8'))
        if (utc_now() - datetime.datetime.fromisoformat(saved['fetched_at'])).total_seconds() < settings.SPATIAL_CACHE_SECONDS:
            return saved, False
    raw = qweather_client.fetch_hourly(latitude=latitude, longitude=longitude)
    saved = {'fetched_at': utc_text(utc_now()), 'data': raw}
    temporary = path.with_suffix('.tmp')
    write_json(temporary, saved)
    os.replace(temporary, path)
    return saved, True


def publish_weather(plan, force=False):
    root = settings.SPATIAL_STORAGE_DIR
    root.mkdir(parents=True, exist_ok=True)
    lock = root / '.publish-lock'
    try:
        lock.mkdir()
    except FileExistsError:
        raise ValueError('A spatial publication is running. If it crashed, verify no publisher runs before removing .publish-lock.') from None
    run_id = 'spatial_' + utc_now().strftime('%Y%m%dT%H%M%SZ_') + uuid.uuid4().hex[:8]
    output = root / run_id
    output.mkdir()
    manifest = {'run_id': run_id, 'status': 'running', 'created_at': utc_text(utc_now()), 'plan': plan, 'source': 'QWeather weather/v1/hourly', 'scene_id': 'scene_shanghai', 'method': 'Delaunay piecewise-linear EPSG:32651; strict valid triangle; no extrapolation', 'actual_calls': 0, 'inputs': [], 'units': {}, 'code_sha256': sha256(__file__), 'math_sha256': sha256(Path(__file__).with_name('spatial_math.py'))}
    try:
        sources = []
        for index, (longitude, latitude) in enumerate(plan['points']):
            saved, called = fetch_cached(longitude, latitude, force)
            manifest['actual_calls'] += int(called)
            path = output / f'source_{index:03}.json'
            write_json(path, saved)
            manifest['inputs'].append({'path': path.name, 'sha256': sha256(path), 'longitude': longitude, 'latitude': latitude, 'fetched_at': saved['fetched_at']})
            sources.append(saved['data'])
        times = sorted(set.intersection(*(set(source['hourly']['time']) for source in sources)))
        if not times:
            raise ValueError('No common forecast times across all query locations.')
        cube = np.full((len(times), len(sources), len(WEATHER_VARIABLES)), np.nan)
        for point_index, source in enumerate(sources):
            hourly = source['hourly']
            indexes = {time: index for index, time in enumerate(hourly['time'])}
            for time_index, moment in enumerate(times):
                source_index = indexes[moment]
                speed = hourly['wind_speed_10m'][source_index]
                direction = hourly['wind_direction_10m'][source_index]
                east, north = wind_components(float('nan') if speed is None else speed, float('nan') if direction is None else direction)
                cube[time_index, point_index] = [hourly['temperature_2m'][source_index], hourly['relative_humidity_2m'][source_index], east, north, hourly.get('dew_point', [None] * len(indexes))[source_index]]
        points = np.asarray(plan['points'])
        if np.linalg.matrix_rank(points - points.mean(axis=0)) < 2:
            raise ValueError('Rounded query points are collinear.')
        east, north = PROJECT.transform(points[:, 0], points[:, 1])
        projected = np.column_stack([east, north])
        bounds = [float(points[:, 0].min()), float(points[:, 1].min()), float(points[:, 0].max()), float(points[:, 1].max())]
        np.savez_compressed(output / 'weather.npz', points=points, projected=projected, values=cube)
        boundary_bytes = boundary_path().read_bytes()
        (output / 'boundary.geojson').write_bytes(boundary_bytes)
        manifest.update({
            'status': 'completed', 'times': [utc_text(datetime.datetime.fromisoformat(moment)) for moment in times], 'bbox': bounds, 'variables': list(WEATHER_VARIABLES),
            'array_sha256': sha256(output / 'weather.npz'), 'boundary_sha256': hashlib.sha256(boundary_bytes).hexdigest(),
            'units': {'air_temperature': '°C', 'relative_humidity': '%', 'wind_east': 'm/s', 'wind_north': 'm/s', 'dew_point': '°C'},
            'attributions': sorted({attribution for source in sources for attribution in source['provider_meta']['attributions']}),
            'valid_counts': np.isfinite(cube).sum(axis=(0, 1)).tolist(),
            'quality': ['Forecast interpolation, not observation or microclimate downscaling.', 'Rounded requests are deduplicated; independent model grid identity is unknown.', 'Only convex-hull and Shanghai-boundary support is displayed.', 'Missing support yields null; no temporal extrapolation.', 'Dew point exceeding temperature is masked; humidity and dew point are not a thermodynamic joint retrieval.'],
        })
        write_json(output / 'manifest.json', manifest)
        (output / 'quality_report.md').write_text(f"# 和风空间插值发布\n\n发布：{run_id}\n\n位置数：{len(points)}；公共时刻数：{len(times)}；实际 API 请求：{manifest['actual_calls']}。\n\n" + '\n'.join(f'- {entry}' for entry in manifest['quality']), encoding='utf-8')
        pointer = root / 'latest.tmp'
        write_json(pointer, {'run_id': run_id})
        os.replace(pointer, root / 'latest.json')
        return manifest
    except Exception as error:
        manifest.update(status='failed', error_type=type(error).__name__, error_message=str(error))
        write_json(output / 'manifest.json', manifest)
        raise
    finally:
        lock.rmdir()


def read_release(run_id=None, pointer_name='latest.json'):
    root = settings.SPATIAL_STORAGE_DIR
    if run_id is None:
        pointer = root / pointer_name
        if not pointer.exists():
            return None
        run_id = json.loads(pointer.read_text(encoding='utf-8'))['run_id']
    if not re.fullmatch(r'spatial_[A-Za-z0-9_]+', run_id):
        raise ValueError('Invalid spatial release ID.')
    directory = root / run_id
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['status'] != 'completed':
        raise ValueError('Spatial release is not complete.')
    return directory, manifest


def sample_release(run_id, time_index, coordinates):
    directory, manifest = read_release(run_id)
    if time_index < 0 or time_index >= len(manifest['times']):
        raise ValueError('Invalid forecast frame.')
    coordinates = np.asarray(coordinates, dtype=float)
    if coordinates.ndim != 2 or coordinates.shape[1] != 2 or not np.isfinite(coordinates).all() or np.any(np.abs(coordinates) > [180, 90]):
        raise ValueError('Invalid WGS84 query coordinates.')
    east, north = PROJECT.transform(coordinates[:, 0], coordinates[:, 1])
    queries = np.column_stack([east, north])
    if manifest.get('kind') == 'tile':
        from app.services.radiation_service import sample_tile
        result = {'net_shortwave_background': sample_tile(np.load(directory / 'net_shortwave.npy', allow_pickle=False), manifest['profile'], coordinates)}
    elif manifest.get('kind') == 'geometry':
        with np.load(directory / 'receivers.npz', allow_pickle=False) as arrays:
            _, nearest = cKDTree(arrays['projected']).query(queries)
            supported = np.all(np.abs(queries - arrays['projected'][nearest]) <= manifest['grid_m'] / 2 + 1e-6, axis=1)
            result = {variable: arrays[variable][nearest].copy() for variable in manifest['display_variables']}
            for values in result.values():
                values[~supported] = np.nan
    elif manifest.get('kind') == 'adjustment_500m':
        with np.load(directory / 'grid_500m.npz', allow_pickle=False) as arrays:
            lons = arrays['lons']
            lats = arrays['lats']
            result = {}
            for variable in manifest['display_variables']:
                if variable in arrays:
                    cube = arrays[variable]
                    field_2d = cube[time_index]
                    interpolator = RegularGridInterpolator((lats, lons), field_2d, bounds_error=False, fill_value=np.nan)
                    result[variable] = interpolator(np.column_stack([coordinates[:, 1], coordinates[:, 0]]))
    else:
        with np.load(directory / 'weather.npz', allow_pickle=False) as arrays:
            values = arrays['values'][time_index]
            result = {variable: interpolate(arrays['projected'], values[:, index], queries) for index, variable in enumerate(WEATHER_VARIABLES)}
        result['wind_speed'], result['wind_direction'] = wind_from_components(result['wind_east'], result['wind_north'])
        result['dew_point'][result['dew_point'] > result['air_temperature'] + .1] = np.nan
    if len(coordinates) >= 100_000:
        mask_dir = directory / 'raster_cache'
        mask_dir.mkdir(exist_ok=True)
        mask_file = mask_dir / f'mask_{len(coordinates)}.npy'
        if mask_file.exists():
            inside = np.load(mask_file)
        else:
            boundary = load_boundary(directory / 'boundary.geojson')
            inside = contains_xy(boundary, coordinates[:, 0], coordinates[:, 1])
            try:
                np.save(mask_file, inside)
            except Exception:
                pass
    else:
        boundary = load_boundary(directory / 'boundary.geojson')
        inside = contains_xy(boundary, coordinates[:, 0], coordinates[:, 1])
    for values in result.values():
        values[~inside] = np.nan
    return result


def sample_release_series(run_id, coordinate, variable):
    directory, manifest = read_release(run_id)
    coordinates = np.asarray(coordinate, dtype=float)
    if coordinates.shape != (2,) or not np.isfinite(coordinates).all() or abs(coordinates[0]) > 180 or abs(coordinates[1]) > 90:
        raise ValueError('Invalid WGS84 query coordinates.')
    longitude, latitude = float(coordinates[0]), float(coordinates[1])

    boundary = load_boundary(directory / 'boundary.geojson')
    inside = contains_xy(boundary, [longitude], [latitude])[0]
    if not inside:
        return [{'time': moment, 'value': None} for moment in manifest['times']]

    if manifest.get('kind') == 'tile':
        from app.services.radiation_service import sample_tile
        data = np.load(directory / 'net_shortwave.npy', allow_pickle=False)
        val = sample_tile(data, manifest['profile'], [[longitude, latitude]])[0]
        v_float = float(val) if np.isfinite(val) else None
        return [{'time': moment, 'value': v_float} for moment in manifest['times']]
    elif manifest.get('kind') == 'geometry':
        east, north = PROJECT.transform([longitude], [latitude])
        queries = np.column_stack([east, north])
        with np.load(directory / 'receivers.npz', allow_pickle=False) as arrays:
            _, nearest = cKDTree(arrays['projected']).query(queries)
            supported = np.all(np.abs(queries - arrays['projected'][nearest]) <= manifest['grid_m'] / 2 + 1e-6, axis=1)[0]
            if not supported or variable not in arrays:
                return [{'time': moment, 'value': None} for moment in manifest['times']]
            cube = arrays[variable]
            if cube.ndim == 2:
                sampled = cube[:, nearest[0]]
                return [{'time': moment, 'value': float(val) if np.isfinite(val) else None} for moment, val in zip(manifest['times'], sampled)]
            else:
                val = float(cube[nearest[0]])
                return [{'time': moment, 'value': val if np.isfinite(val) else None} for moment in manifest['times']]
    elif manifest.get('kind') == 'adjustment_500m':
        with np.load(directory / 'grid_500m.npz', allow_pickle=False) as arrays:
            if variable not in arrays:
                raise ValueError(f"Variable '{variable}' not found in release.")
            lons = arrays['lons']
            lats = arrays['lats']
            cube = arrays[variable]
            cube_t = np.moveaxis(cube, 0, -1)
            interpolator = RegularGridInterpolator((lats, lons), cube_t, bounds_error=False, fill_value=np.nan)
            sampled = interpolator([[latitude, longitude]])[0]
            points = []
            for moment, val in zip(manifest['times'], sampled):
                points.append({'time': moment, 'value': float(val) if np.isfinite(val) else None})
            return points
    else:
        east, north = PROJECT.transform([longitude], [latitude])
        queries = np.column_stack([east, north])
        with np.load(directory / 'weather.npz', allow_pickle=False) as arrays:
            projected = arrays['projected']
            all_values = arrays['values']
            points = []
            for time_index, moment in enumerate(manifest['times']):
                values = all_values[time_index]
                res = {var: interpolate(projected, values[:, idx], queries)[0] for idx, var in enumerate(WEATHER_VARIABLES)}
                wind_speed, wind_dir = wind_from_components(np.array([res['wind_east']]), np.array([res['wind_north']]))
                res['wind_speed'] = float(wind_speed[0])
                res['wind_direction'] = float(wind_dir[0])
                if res.get('dew_point') is not None and res.get('air_temperature') is not None and res['dew_point'] > res['air_temperature'] + 0.1:
                    res['dew_point'] = np.nan
                val = res.get(variable, np.nan)
                points.append({'time': moment, 'value': float(val) if np.isfinite(val) else None})
            return points


def resolve_dynamic_legend(variable, run_id=None, frame=None):
    default_name, unit, def_min, def_max, colors = VARIABLES[variable]
    if run_id is None or frame is None:
        return {'min': def_min, 'max': def_max, 'colors': colors}
    try:
        directory, manifest = read_release(run_id)
        if manifest.get('kind') == 'adjustment_500m':
            with np.load(directory / 'grid_500m.npz', allow_pickle=False) as arrays:
                if variable in arrays:
                    cube = arrays[variable]
                    if 0 <= frame < len(cube):
                        slice_data = cube[frame]
                        valid = np.isfinite(slice_data)
                        if np.any(valid):
                            p1 = float(np.nanpercentile(slice_data[valid], 1.0))
                            p99 = float(np.nanpercentile(slice_data[valid], 99.0))
                            vmin = round(p1, 1)
                            vmax = round(p99, 1)
                            if vmax - vmin < 1.0:
                                mid = round((p1 + p99) / 2.0, 1)
                                vmin = round(mid - 0.6, 1)
                                vmax = round(mid + 0.6, 1)
                            return {'min': vmin, 'max': vmax, 'colors': colors}
        elif manifest.get('kind') not in ('tile', 'geometry'):
            with np.load(directory / 'weather.npz', allow_pickle=False) as arrays:
                if 'values' in arrays and variable in WEATHER_VARIABLES:
                    var_idx = WEATHER_VARIABLES.index(variable)
                    slice_data = arrays['values'][frame, :, var_idx]
                    valid = np.isfinite(slice_data)
                    if np.any(valid):
                        p1 = float(np.nanpercentile(slice_data[valid], 1.0))
                        p99 = float(np.nanpercentile(slice_data[valid], 99.0))
                        vmin = round(p1, 1)
                        vmax = round(p99, 1)
                        if vmax - vmin < 1.0:
                            mid = round((p1 + p99) / 2.0, 1)
                            vmin = round(mid - 0.6, 1)
                            vmax = round(mid + 0.6, 1)
                        return {'min': vmin, 'max': vmax, 'colors': colors}
    except Exception:
        pass
    return {'min': def_min, 'max': def_max, 'colors': colors}


def legend(variable, run_id=None, frame=None):
    return resolve_dynamic_legend(variable, run_id, frame)


def published_products():
    products = {}
    for pointer in ('latest.json', 'latest_tile.json', 'latest_geometry.json'):
        release = read_release(pointer_name=pointer)
        if release:
            _, manifest = release
            for variable in manifest.get('display_variables', ['air_temperature', 'relative_humidity', 'wind_speed', 'dew_point']):
                products[variable] = manifest
    return products


def catalog():
    products = published_products()
    if not products:
        return None
    return {'products': [{'variable': variable, 'name': VARIABLES[variable][0], 'unit': VARIABLES[variable][1], 'product_id': 'qweather_spatial', 'availability': 'available', 'definition': manifest['method'], 'times': manifest['times'], 'legend': legend(variable)} for variable, manifest in products.items()]}


def create_view(time_selection, variables):
    products = published_products()
    now = utc_now()
    if time_selection.get('kind') not in ('now', 'at') or (time_selection['kind'] == 'at' and not time_selection.get('time')):
        raise ValueError('Use now or at with an explicit RFC3339 time.')
    requested = now if time_selection['kind'] == 'now' else datetime.datetime.fromisoformat(time_selection['time'].replace('Z', '+00:00'))
    if requested.tzinfo is None:
        raise ValueError('View time must include timezone.')
    view_id = 'sp_' + uuid.uuid4().hex
    expires = utc_text(now + datetime.timedelta(hours=24))
    items = []
    for variable in variables:
        if variable not in products:
            continue
        manifest = products[variable]
        times = [datetime.datetime.fromisoformat(moment) for moment in manifest['times']]
        frame = min(range(len(times)), key=lambda index: abs((times[index] - requested).total_seconds()))
        tolerance = datetime.timedelta(hours=1) if not manifest.get('kind') else datetime.timedelta(seconds=1)
        supported = times[0] - tolerance <= requested <= times[-1] + tolerance
        stale = (now - datetime.datetime.fromisoformat(manifest['created_at'])).total_seconds() > 3 * 3600
        support = manifest.get('spatial_support') or f"{len(manifest['plan']['points'])} 个查询位置，计划间距 {manifest['plan']['requested_spacing_m']} m；请求坐标保留两位小数；三角网插值，不外推。"
        items.append({
            'variable': variable, 'product_id': 'qweather_spatial', 'release_id': manifest['run_id'], 'unit': VARIABLES[variable][1],
            'frame': frame,
            'availability': 'available' if supported else 'missing', 'freshness': 'stale' if stale else 'fresh', 'reason_code': None if supported else 'outside_time_range',
            'requested_time': utc_text(requested), 'resolved_time': utc_text(times[frame]) if supported else None, 'interval_start': manifest.get('profile', {}).get('interval_start'), 'interval_end': manifest.get('profile', {}).get('interval_end'), 'temporal_support': manifest.get('profile', {}).get('temporal_support', 'instant'),
            'legend': legend(variable, manifest['run_id'], frame), 'assets': [{'type': 'image', 'url': f"/api/v1/spatial/releases/{manifest['run_id']}/raster/{variable}/{frame}.png", 'bbox': manifest['bbox'], 'attribution': 'QWeather'}] if supported else [],
            'provenance': {'source': manifest['source'] + '；' + '；'.join(manifest['attributions']), 'spatial_support': support, 'receiver_height': manifest.get('receiver_height', '供应商未声明；非街谷或人体热暴露模型'), 'model_version': manifest['run_id'], 'omissions': manifest['quality']},
        })
    view = {'view_id': view_id, 'requested_time': utc_text(requested), 'expires_at': expires, 'mode': 'historical' if requested < now - datetime.timedelta(hours=1) else 'forecast', 'items': items}
    directory = settings.SPATIAL_STORAGE_DIR / 'views'
    directory.mkdir(exist_ok=True)
    write_json(directory / f'{view_id}.json', view)
    return view


def read_view(view_id):
    if not re.fullmatch(r'sp_[a-f0-9]{32}', view_id):
        raise ValueError('Invalid spatial view ID.')
    view = json.loads((settings.SPATIAL_STORAGE_DIR / 'views' / f'{view_id}.json').read_text(encoding='utf-8'))
    if datetime.datetime.fromisoformat(view['expires_at'].replace('Z', '+00:00')) <= utc_now():
        raise TimeoutError('Spatial view expired.')
    return view


def point_result(view_id, longitude, latitude):
    view = read_view(view_id)
    items = []
    sampled = {}
    for item in view['items']:
        key = (item['release_id'], item['frame'])
        if key not in sampled:
            sampled[key] = sample_release(*key, [[longitude, latitude]])
        values = sampled[key] if item['availability'] == 'available' else {}
        value = float(values[item['variable']][0]) if item['variable'] in values else float('nan')
        items.append({**item, 'value': value if np.isfinite(value) else None, 'value_status': 'valid' if np.isfinite(value) else 'no_data', 'reason_code': None if np.isfinite(value) else 'outside_support_or_missing'})
    return {'view_id': view_id, 'location': {'type': 'Point', 'coordinates': [longitude, latitude]}, 'items': items}


def raster_png(run_id, variable, frame, size=1024):
    if variable not in VARIABLES:
        raise ValueError('Unsupported map variable.')
    directory, manifest = read_release(run_id)
    cache_dir = directory / 'raster_cache'
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / f'{variable}_{frame}_{size}.png'
    if cache_file.exists():
        return cache_file.read_bytes()

    west, south, east, north = manifest['bbox']
    longitude = west + (np.arange(size) + .5) / size * (east - west)
    latitude = north - (np.arange(size) + .5) / size * (north - south)
    lon_grid, lat_grid = np.meshgrid(longitude, latitude)
    coordinates = np.column_stack([lon_grid.ravel(), lat_grid.ravel()])
    values = sample_release(run_id, frame, coordinates).get(variable)
    if values is None:
        raise ValueError('Variable is unavailable in this release.')
    config = legend(variable, run_id, frame)
    colors = np.array([[int(color[offset:offset + 2], 16) for offset in (1, 3, 5)] for color in config['colors']])
    v_min = config['min']
    v_max = config['max']
    denom = v_max - v_min if v_max > v_min else 1.0
    fraction = np.clip((np.nan_to_num(values, nan=v_min) - v_min) / denom, 0, 1)
    rgba = np.zeros((len(values), 4), dtype=np.uint8)
    for channel in range(3):
        rgba[:, channel] = np.interp(fraction, np.linspace(0, 1, len(colors)), colors[:, channel]).astype(np.uint8)
    rgba[:, 3] = np.where(np.isfinite(values), 245, 0)
    output = io.BytesIO()
    Image.fromarray(rgba.reshape(size, size, 4)).save(output, format='PNG')
    data = output.getvalue()
    try:
        cache_file.write_bytes(data)
    except Exception:
        pass
    return data

