"""Environment exploration, catalog, fixed views, point and series queries router."""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from app.services import spatial_service as spatial
from app.routers.spatial import translate_error
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import format_utc_z, make_api_response
from app.schemas.environment import CreateViewRequest
from app.services.env_service import (
    create_fixed_view,
    get_environment_catalog,
    get_fixed_view,
    get_point_reading,
    get_series_readings,
    list_scene_releases,
)

router = APIRouter(tags=["A02 环境探索"])


@router.get("/scenes/{scene_id}/environment/catalog")
def get_catalog(
    scene_id: str,
    request: Request,
):
    request_id = getattr(request.state, "request_id", "req_env_catalog")
    if scene_id == 'scene_shanghai':
        published = spatial.catalog()
        if published:
            return make_api_response(published, request_id)
    catalogs = get_environment_catalog(scene_id)
    return make_api_response([c.model_dump() for c in catalogs], request_id)


@router.get("/scenes/{scene_id}/environment/releases")
def get_releases(
    scene_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_env_releases")
    releases = list_scene_releases(db, scene_id)
    return make_api_response([r.model_dump() for r in releases], request_id)


@router.post("/scenes/{scene_id}/environment/views")
def post_view(
    scene_id: str,
    req: CreateViewRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_create_view")
    req.scene_id = scene_id
    if scene_id == 'scene_shanghai' and req.release_selection.mode != 'pinned' and spatial.catalog():
        try:
            return make_api_response(spatial.create_view(req.time_selection.model_dump(), req.variables), request_id)
        except (ValueError, FileNotFoundError) as error:
            raise translate_error(error) from None
    view_resp = create_fixed_view(db, req)
    return make_api_response(view_resp.model_dump(), request_id)


@router.get("/environment/views/{view_id}")
def get_view_details(
    view_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_view_detail")
    if view_id.startswith('sp_'):
        try:
            return make_api_response(spatial.read_view(view_id), request_id)
        except (ValueError, FileNotFoundError, TimeoutError) as error:
            raise translate_error(error) from None
    view = get_fixed_view(db, view_id)
    return make_api_response(
        {
            "view_id": view.id,
            "scene_id": view.scene_id,
            "requested_time": format_utc_z(view.requested_time),
            "resolved_time": format_utc_z(view.resolved_time),
            "time_selection_kind": view.time_selection_kind,
            "release_selection_mode": view.release_selection_mode,
            "variables": view.variables,
            "pinned_releases": view.pinned_releases,
            "expires_at": format_utc_z(view.expires_at),
        },
        request_id,
    )


@router.get("/environment/views/{view_id}/point")
def get_point(
    view_id: str,
    request: Request,
    longitude: float = Query(..., description="Longitude in EPSG:4326"),
    latitude: float = Query(..., description="Latitude in EPSG:4326"),
    db: Session = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_view_point")
    if view_id.startswith('sp_'):
        try:
            return make_api_response(spatial.point_result(view_id, longitude, latitude), request_id)
        except (ValueError, FileNotFoundError, TimeoutError) as error:
            raise translate_error(error) from None
    point_resp = get_point_reading(db, view_id, lon=longitude, lat=latitude)
    return make_api_response(point_resp.model_dump(), request_id)


@router.get("/environment/views/{view_id}/series")
def get_series(
    view_id: str,
    request: Request,
    longitude: float = Query(..., description="Longitude"),
    latitude: float = Query(..., description="Latitude"),
    start_time: str = Query(..., description="RFC 3339 start timestamp"),
    end_time: str = Query(..., description="RFC 3339 end timestamp"),
    variables: Optional[str] = Query(None, description="Comma-separated variable names"),
    db: Session = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_view_series")
    var_list = [v.strip() for v in variables.split(",")] if variables else None
    series_resp = get_series_readings(
        db,
        view_id,
        lon=longitude,
        lat=latitude,
        start_time=start_time,
        end_time=end_time,
        variables=var_list,
    )
    return make_api_response(series_resp.model_dump(), request_id)
