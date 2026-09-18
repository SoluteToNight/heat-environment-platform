import datetime
import hashlib
import io
import json
import math
import struct
from pathlib import Path

import numpy as np
from PIL import Image
from pyproj import Transformer
from scipy.ndimage import map_coordinates
from shapely.geometry import shape, Point
from shapely.ops import transform

from app.services.spatial_math import PROJECT, EXCHANGE, solar_position, ray_visibility, sky_factor, local_shortwave


def decode_tile(content, profile):
    required = ('verified', 'evidence', 'width', 'height', 'header_offset', 'header_stride', 'data_x', 'data_y', 'data_width', 'data_height', 'nodata_codes', 'quantity', 'unit', 'valid_time', 'temporal_support', 'z', 'x', 'y')
    if any(key not in profile for key in required) or profile['verified'] is not True or not profile['evidence']:
        raise ValueError('A verified tile profile with evidence, data offsets, NoData and time semantics is required.')
    if profile['quantity'] != 'net_shortwave' or profile['unit'] != 'W/m²':
        raise ValueError('This decoder accepts verified net shortwave W/m² only.')
    moment = datetime.datetime.fromisoformat(profile['valid_time'].replace('Z', '+00:00'))
    if moment.tzinfo is None:
        raise ValueError('Tile valid_time needs timezone.')
    if profile['temporal_support'] not in ('instant', 'interval_mean', 'unknown'):
        raise ValueError('Unknown temporal support.')
    if profile['temporal_support'] == 'interval_mean':
        start = datetime.datetime.fromisoformat(profile['interval_start'].replace('Z', '+00:00'))
        end = datetime.datetime.fromisoformat(profile['interval_end'].replace('Z', '+00:00'))
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise ValueError('Invalid radiation interval.')
    pixels = np.asarray(Image.open(io.BytesIO(content)).convert('RGBA'))
    if pixels.shape[:2] != (profile['height'], profile['width']):
        raise ValueError('Tile shape differs from the verified profile.')
    raw = pixels.ravel()
    header = bytearray()
    for index in range(28):
        offset = profile['header_offset'] + index * profile['header_stride']
        channels = raw[offset:offset + 3].astype(float)
        if len(channels) != 3:
            raise ValueError('Header extends beyond image.')
        red, green, blue = np.rint(channels / [64, 16, 64]).astype(int)
        if not (0 <= red <= 3 and 0 <= green <= 15 and 0 <= blue <= 3):
            raise ValueError('Corrupted tile header.')
        header.append((red << 6) | (green << 2) | blue)
    parameters = struct.unpack('<7f', header)
    minimum, maximum = parameters[:2]
    if not np.isfinite(parameters).all() or maximum < minimum:
        raise ValueError('Invalid tile scale parameters.')
    data_x, data_y = profile['data_x'], profile['data_y']
    width, height = profile['data_width'], profile['data_height']
    if min(width, height) <= 0 or min(data_x, data_y) < 0 or data_x + width > pixels.shape[1] or data_y + height > pixels.shape[0]:
        raise ValueError('Data rectangle extends beyond tile.')
    for index in range(28):
        header_pixel = (profile['header_offset'] + index * profile['header_stride']) // 4
        header_row, header_column = divmod(header_pixel, pixels.shape[1])
        if data_x <= header_column < data_x + width and data_y <= header_row < data_y + height:
            raise ValueError('Data rectangle overlaps the control header.')
    codes = pixels[data_y:data_y + height, data_x:data_x + width, 0]
    values = codes.astype(float) * ((maximum - minimum) / 255) + minimum
    values[np.isin(codes, profile['nodata_codes'])] = np.nan
    return values, {'min': minimum, 'max': maximum, 'parameters': parameters, 'source_sha256': hashlib.sha256(content).hexdigest(), 'profile': profile}


def sample_tile(values, profile, coordinates):
    coordinates = np.asarray(coordinates)
    longitude, latitude = coordinates[:, 0], coordinates[:, 1]
    tile_count = 2 ** profile['z']
    nodes = profile.get('registration') == 'grid_nodes_with_border'
    width = values.shape[1] - 1 if nodes else values.shape[1]
    height = values.shape[0] - 1 if nodes else values.shape[0]
    offset = 0 if nodes else .5
    columns = ((longitude + 180) / 360 * tile_count - profile['x']) * width - offset
    rows = ((1 - np.arcsinh(np.tan(np.deg2rad(latitude))) / np.pi) / 2 * tile_count - profile['y']) * height - offset
    return map_coordinates(values, [rows, columns], order=1, mode='constant', cval=np.nan, prefilter=False)


def compute_geometry(bounds, buildings_geojson, moment, grid_m=30, receiver_height=1.1, radius=500, sky_azimuths=24, sky_elevations=8):
    if grid_m < 5 or grid_m > 100 or radius <= 0 or receiver_height < 0:
        raise ValueError('Invalid geometry computation parameters.')
    west, south, east, north = bounds
    if west >= east or south >= north:
        raise ValueError('Invalid bounds.')
    minimum_east, minimum_north = PROJECT.transform(west, south)
    maximum_east, maximum_north = PROJECT.transform(east, north)
    eastings = np.arange(minimum_east + grid_m / 2, maximum_east, grid_m)
    northings = np.arange(minimum_north + grid_m / 2, maximum_north, grid_m)
    if len(eastings) * len(northings) > 10000:
        raise ValueError('Pilot limit is 10,000 receiver points.')
    collection = json.loads(Path(buildings_geojson).read_text(encoding='utf-8-sig'))
    if collection.get('type') != 'FeatureCollection':
        raise ValueError('Buildings must be a WGS84 GeoJSON FeatureCollection with height_m.')
    buildings = []
    for feature in collection['features']:
        geometry = shape(feature['geometry'])
        if geometry.geom_type not in ('Polygon', 'MultiPolygon') or not geometry.is_valid:
            raise ValueError('Buildings require valid polygon geometry.')
        height = feature.get('properties', {}).get('height_m')
        if height is not None and (not isinstance(height, (int, float)) or not math.isfinite(height) or height <= 0):
            raise ValueError('Building height_m must be positive metres or null.')
        buildings.append((transform(PROJECT.transform, geometry), height))
    receivers = []
    for northing in northings:
        for easting in eastings:
            longitude, latitude = EXCHANGE.transform(easting, northing)
            point = Point(easting, northing)
            indoors = any(polygon.covers(point) for polygon, _ in buildings)
            azimuth, elevation = solar_position(longitude, latitude, moment)
            sun = np.nan if indoors else ray_visibility(easting, northing, receiver_height, azimuth, elevation, buildings, radius)
            sky = np.nan if indoors else sky_factor(easting, northing, receiver_height, buildings, radius, sky_azimuths, sky_elevations)
            receivers.append({'longitude': longitude, 'latitude': latitude, 'sun_visibility': None if not np.isfinite(sun) else sun, 'sky_factor': None if not np.isfinite(sky) else sky, 'solar_elevation_radians': elevation, 'inside_building': indoors})
    return receivers


def downscale_components(receivers, dni, dhi, input_quantity, temporal_support):
    if input_quantity != 'dni_dhi' or temporal_support != 'instant':
        raise ValueError('Instant matched DNI/DHI required; net shortwave and interval means cannot enter this instantaneous solver.')
    for receiver in receivers:
        receiver['local_downwelling_shortwave'] = local_shortwave(dni, dhi, receiver['solar_elevation_radians'], receiver['sun_visibility'], receiver['sky_factor'])
    return receivers
