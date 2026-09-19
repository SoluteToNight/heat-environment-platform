import csv
import io

import numpy as np
from fastapi import APIRouter, HTTPException, Query, Response

from app.services import spatial_service as spatial
from app.schemas.common import make_api_response


router = APIRouter(prefix='/spatial', tags=['空间插值发布'])


def translate_error(error):
    if isinstance(error, FileNotFoundError):
        return HTTPException(404, 'Spatial release or view not found.')
    if isinstance(error, TimeoutError):
        return HTTPException(410, 'Spatial view expired.')
    return HTTPException(422, str(error))


@router.get('/releases/{run_id}/raster/{variable}/{frame}.png')
def raster(run_id: str, variable: str, frame: str, size: int = Query(default=512, ge=128, le=2048)):
    try:
        return Response(spatial.raster_png(run_id, variable, float(frame), size=size), media_type='image/png', headers={'Cache-Control': 'public, max-age=86400'})
    except (ValueError, FileNotFoundError) as error:
        raise translate_error(error) from None


@router.get('/releases/{run_id}/manifest')
def manifest(run_id: str):
    try:
        return make_api_response(spatial.read_release(run_id)[1], 'spatial_manifest')
    except (ValueError, FileNotFoundError) as error:
        raise translate_error(error) from None


@router.get('/views/{view_id}/series')
def series(view_id: str, longitude: float = Query(ge=-180, le=180), latitude: float = Query(ge=-90, le=90), variable: str = 'air_temperature'):
    try:
        view = spatial.read_view(view_id)
        item = next((item for item in view['items'] if item['variable'] == variable), None)
        if item is None:
            raise ValueError('Variable is not included in this fixed view.')
        points = spatial.sample_release_series(item['release_id'], [longitude, latitude], variable)
        return make_api_response({'view_id': view_id, 'variable': variable, 'unit': spatial.VARIABLES[variable][1], 'points': points}, 'spatial_series')
    except (ValueError, FileNotFoundError, TimeoutError) as error:
        raise translate_error(error) from None


@router.get('/views/{view_id}/export.csv')
def export(view_id: str, longitude: float = Query(ge=-180, le=180), latitude: float = Query(ge=-90, le=90), variable: str = 'air_temperature'):
    result = series(view_id, longitude, latitude, variable)['data']
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(['view_id', 'longitude', 'latitude', 'time_utc', 'variable', 'unit', 'value', 'status'])
    for point in result['points']:
        writer.writerow([view_id, longitude, latitude, point['time'], variable, result['unit'], point['value'], 'valid' if point['value'] is not None else 'no_data'])
    return Response(stream.getvalue().encode('utf-8-sig'), media_type='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename="{view_id}.csv"', 'Cache-Control': 'no-store'})
