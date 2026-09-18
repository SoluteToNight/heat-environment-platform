"""Scenes, layers, places, and spatial features router."""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import make_api_response
from app.services.scene_service import (
    get_feature_by_id,
    get_scene_by_id,
    list_scene_layers,
    list_scenes,
    query_scene_features,
    search_scene_places,
)

router = APIRouter(prefix="/scenes", tags=["A01 场景与图层目录"])


@router.get("")
def get_scenes(
    request: Request,
    db: Session = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_scenes")
    scenes = list_scenes(db)
    return make_api_response([s.model_dump() for s in scenes], request_id)


@router.get("/{scene_id}")
def get_scene(
    scene_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_scene_detail")
    scene = get_scene_by_id(db, scene_id)
    return make_api_response(scene.model_dump(), request_id)


@router.get("/{scene_id}/layers")
def get_layers(
    scene_id: str,
    request: Request,
):
    request_id = getattr(request.state, "request_id", "req_layers")
    layers = list_scene_layers(scene_id)
    return make_api_response([ly.model_dump() for ly in layers], request_id)


@router.get("/{scene_id}/places")
def search_places(
    scene_id: str,
    request: Request,
    q: Optional[str] = Query(None, description="Keyword for name/amenity"),
    bbox: Optional[str] = Query(None, description="min_lon,min_lat,max_lon,max_lat"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_places")
    bbox_coords = None
    if bbox:
        try:
            bbox_coords = [float(x.strip()) for x in bbox.split(",")]
        except Exception:
            pass

    places = search_scene_places(db, scene_id, q=q, bbox=bbox_coords, limit=limit, offset=offset)
    return make_api_response([p.model_dump() for p in places], request_id)


@router.get("/{scene_id}/features")
def get_features(
    scene_id: str,
    request: Request,
    layer_id: str = Query(..., description="Layer ID (layer_admin, layer_buildings, layer_roads, layer_water, layer_green)"),
    bbox: Optional[str] = Query(None, description="min_lon,min_lat,max_lon,max_lat"),
    min_height: Optional[float] = Query(None, description="Minimum building height filter for LOD"),
    limit: int = Query(50, ge=1, le=3000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_features")
    bbox_coords = None
    if bbox:
        try:
            bbox_coords = [float(x.strip()) for x in bbox.split(",")]
        except Exception:
            pass

    features = query_scene_features(db, scene_id, layer_id, bbox=bbox_coords, min_height=min_height, limit=limit, offset=offset)
    return make_api_response([f.model_dump() for f in features], request_id)


@router.get("/{scene_id}/features/{feature_id}")
def get_feature(
    scene_id: str,
    feature_id: str,
    layer_id: str = Query(..., description="Layer ID"),
    request: Request = None,
    db: Session = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_feature_detail")
    feature = get_feature_by_id(db, layer_id, feature_id)
    return make_api_response(feature.model_dump(), request_id)
