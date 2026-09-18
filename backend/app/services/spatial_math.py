import datetime
import math

import numpy as np
from pyproj import Transformer
from scipy.spatial import Delaunay
from shapely.geometry import Point, LineString


PROJECT = Transformer.from_crs(4326, 32651, always_xy=True)
EXCHANGE = Transformer.from_crs(32651, 4326, always_xy=True)


def interpolate(points, values, queries):
    points = np.asarray(points, dtype=float)
    values = np.asarray(values, dtype=float)
    queries = np.asarray(queries, dtype=float)
    triangulation = Delaunay(points)
    simplex = triangulation.find_simplex(queries, tol=1e-9)
    output = np.full(len(queries), np.nan)
    inside = simplex >= 0
    transforms = triangulation.transform[simplex[inside]]
    barycentric = np.einsum('ijk,ik->ij', transforms[:, :2], queries[inside] - transforms[:, 2])
    weights = np.column_stack([barycentric, 1 - barycentric.sum(axis=1)])
    corners = values[triangulation.simplices[simplex[inside]]]
    valid = np.isfinite(corners).all(axis=1)
    interpolated = np.sum(corners * weights, axis=1)
    interpolated[~valid] = np.nan
    output[inside] = interpolated
    for point, value in zip(points, values):
        exact = np.linalg.norm(queries - point, axis=1) < 1e-6
        output[exact] = value
    return output


def wind_components(speed, direction):
    radians = np.deg2rad(direction)
    speed = np.asarray(speed, dtype=float)
    east = -speed * np.sin(radians)
    north = -speed * np.cos(radians)
    return np.where(speed == 0, 0, east), np.where(speed == 0, 0, north)


def wind_from_components(east, north):
    speed = np.hypot(east, north)
    direction = np.mod(np.rad2deg(np.arctan2(-east, -north)), 360)
    return speed, np.where(speed < 1e-6, np.nan, direction)


def solar_position(longitude, latitude, moment):
    if moment.tzinfo is None:
        raise ValueError('Solar calculation requires a timezone-aware time.')
    moment = moment.astimezone(datetime.timezone.utc)
    day = moment.timetuple().tm_yday
    hour = moment.hour + moment.minute / 60 + moment.second / 3600
    year_days = 366 if moment.year % 4 == 0 and (moment.year % 100 != 0 or moment.year % 400 == 0) else 365
    gamma = 2 * math.pi / year_days * (day - 1 + (hour - 12) / 24)
    equation = 229.18 * (.000075 + .001868 * math.cos(gamma) - .032077 * math.sin(gamma) - .014615 * math.cos(2 * gamma) - .040849 * math.sin(2 * gamma))
    declination = .006918 - .399912 * math.cos(gamma) + .070257 * math.sin(gamma) - .006758 * math.cos(2 * gamma) + .000907 * math.sin(2 * gamma) - .002697 * math.cos(3 * gamma) + .00148 * math.sin(3 * gamma)
    hour_angle = math.radians(((hour * 60 + equation + 4 * longitude) % 1440) / 4 - 180)
    lat = math.radians(latitude)
    cos_zenith = np.clip(math.sin(lat) * math.sin(declination) + math.cos(lat) * math.cos(declination) * math.cos(hour_angle), -1, 1)
    elevation = math.asin(cos_zenith)
    azimuth = (math.atan2(math.sin(hour_angle), math.cos(hour_angle) * math.sin(lat) - math.tan(declination) * math.cos(lat)) + math.pi) % (2 * math.pi)
    return azimuth, elevation


def ray_visibility(easting, northing, receiver_height, azimuth, elevation, buildings, radius):
    if elevation <= 0:
        return 0.0
    origin = Point(easting, northing)
    ray = LineString([(easting, northing), (easting + radius * math.sin(azimuth), northing + radius * math.cos(azimuth))])
    uncertain = False
    for polygon, height in buildings:
        if not polygon.intersects(ray):
            continue
        if height is None:
            uncertain = True
            continue
        distance = origin.distance(polygon.intersection(ray))
        if height > receiver_height + distance * math.tan(elevation):
            return 0.0
    return float('nan') if uncertain else 1.0


def sky_factor(easting, northing, receiver_height, buildings, radius, azimuth_samples=24, elevation_samples=8):
    values = []
    for band in range(elevation_samples):
        elevation = math.asin(math.sqrt((band + .5) / elevation_samples))
        for sector in range(azimuth_samples):
            azimuth = (sector + .5) * 2 * math.pi / azimuth_samples
            values.append(ray_visibility(easting, northing, receiver_height, azimuth, elevation, buildings, radius))
    return float(np.mean(values))


def local_shortwave(dni, dhi, elevation, sun_transmission, sky_transmission):
    values = np.asarray([dni, dhi, sun_transmission, sky_transmission], dtype=float)
    if not np.isfinite(values).all():
        return None
    if min(dni, dhi) < 0 or not 0 <= sun_transmission <= 1 or not 0 <= sky_transmission <= 1:
        raise ValueError('Invalid radiation or transmission input.')
    return float(dni * max(0, math.sin(elevation)) * sun_transmission + dhi * sky_transmission)
