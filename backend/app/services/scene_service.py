"""Scene, layers, places, and spatial feature services."""
import json
from typing import Any, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.config import settings
from app.db.models import Scene
from app.schemas.scene import LayerInfo, PlaceItem, FeatureItem, SceneDetail, SceneListItem


# Default scene layers metadata
PREDEFINED_LAYERS = [
    LayerInfo(
        layer_id="layer_admin",
        name="行政区划边界",
        type="vector",
        attribution="OpenStreetMap & 上海市民政地理数据",
        description="上海市域边界及16个行政区区界多边形",
        is_visible_default=True,
    ),
    LayerInfo(
        layer_id="layer_dem",
        name="地形起伏与标高",
        type="raster",
        attribution="ALOS PALSAR 12.5m (DSM地表模型)",
        description="上海全域 12.5m 表面模型与山体阴影（注：含建筑物与树冠表面，未剥离建筑物高度，不作为建筑地基高程基准）",
        is_visible_default=False,
    ),
    LayerInfo(
        layer_id="layer_buildings",
        name="上海高精三维建筑",
        type="vector",
        attribution="上海市高精度参数化3D模型 (本地PostGIS)",
        description="上海市域15.5万栋精准拉伸三维建筑，具备真实物理高度、层数与体积（平原基准拉伸，已剥离未去建筑高度的DEM基准）",
        is_visible_default=True,
    ),
    LayerInfo(
        layer_id="layer_roads",
        name="城市路网",
        type="vector",
        attribution="OpenStreetMap 2026",
        description="等级路网要素",
        is_visible_default=True,
    ),
    LayerInfo(
        layer_id="layer_water",
        name="水系水体",
        type="vector",
        attribution="OpenStreetMap 2026",
        description="河流、湖泊及海岸线水体",
        is_visible_default=True,
    ),
    LayerInfo(
        layer_id="layer_green",
        name="绿地与公园",
        type="vector",
        attribution="OpenStreetMap 2026",
        description="城市绿化、森林公园与公共绿地",
        is_visible_default=True,
    ),
]


def list_scenes(db: Session) -> list[SceneListItem]:
    scenes = db.query(Scene).filter(Scene.status == "active").all()
    return [
        SceneListItem(
            id=s.id,
            name=s.name,
            status=s.status,
            center=[s.center_lon, s.center_lat],
            bbox=s.bbox,
        )
        for s in scenes
    ]


def get_scene_by_id(db: Session, scene_id: str) -> SceneDetail:
    scene = db.query(Scene).filter(Scene.id == scene_id).first()
    if not scene:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scene '{scene_id}' not found",
        )
    return SceneDetail(
        id=scene.id,
        name=scene.name,
        description=scene.description,
        center=[scene.center_lon, scene.center_lat],
        bbox=scene.bbox,
        status=scene.status,
        timezone="Asia/Shanghai",
        tianditu_key=settings.TIANDITU_KEY or None,
    )


def list_scene_layers(scene_id: str) -> list[LayerInfo]:
    return PREDEFINED_LAYERS


def search_scene_places(
    db: Session,
    scene_id: str,
    q: Optional[str] = None,
    bbox: Optional[list[float]] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[PlaceItem]:
    limit = min(max(1, limit), 200)
    clauses = ["geom IS NOT NULL"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}

    if q and q.strip():
        clauses.append("(name ILIKE :q OR amenity ILIKE :q)")
        params["q"] = f"%{q.strip()}%"

    if bbox and len(bbox) == 4:
        clauses.append("geom && ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)")
        params["min_lon"] = bbox[0]
        params["min_lat"] = bbox[1]
        params["max_lon"] = bbox[2]
        params["max_lat"] = bbox[3]

    where_sql = " AND ".join(clauses)
    sql = text(f"""
        SELECT poi_id, name, amenity, ST_X(geom) as lon, ST_Y(geom) as lat
        FROM public.osm_poi
        WHERE {where_sql}
        ORDER BY poi_id
        LIMIT :limit OFFSET :offset;
    """)

    rows = db.execute(sql, params).fetchall()
    return [
        PlaceItem(
            id=str(r[0]),
            title=str(r[1] or "未命名地点"),
            poi_type=r[2],
            lon=float(r[3]),
            lat=float(r[4]),
        )
        for r in rows
    ]


def query_scene_features(
    db: Session,
    scene_id: str,
    layer_id: str,
    bbox: Optional[list[float]] = None,
    min_height: Optional[float] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[FeatureItem]:
    max_limit = 3000 if layer_id == "layer_buildings" else 500
    limit = min(max(1, limit), max_limit)

    # Determine underlying table
    table_map = {
        "layer_admin": ("public.base_admin_boundary", "admin_id", ["name", "admin_level", "area_km2"]),
        "layer_buildings": ("public.osm_buildings", "building_id", ["name", "building", "height", "levels", "height_m", "height_source", "area_m2", "volume_m3"]),
        "layer_roads": ("public.osm_roads", "road_id", ["name", "highway", "length_m"]),
        "layer_water": ("public.osm_water", "water_id", ["name", "water_type", "natural_type", "waterway"]),
        "layer_green": ("public.osm_green", "green_id", ["name", "leisure", "landuse"]),
    }

    if layer_id not in table_map:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Layer '{layer_id}' not found",
        )

    table_name, id_col, prop_cols = table_map[layer_id]
    clauses = ["geom IS NOT NULL"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}

    if bbox and len(bbox) == 4:
        clauses.append("geom && ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)")
        params["min_lon"] = bbox[0]
        params["min_lat"] = bbox[1]
        params["max_lon"] = bbox[2]
        params["max_lat"] = bbox[3]

    if layer_id == "layer_buildings":
        if min_height is not None and min_height > 0:
            clauses.append("COALESCE(height_m, height, levels * 3.5, 12) >= :min_height")
            params["min_height"] = float(min_height)
        order_clause = 'COALESCE(height_m, height, levels * 3.5, 12) DESC, "building_id"'
    elif layer_id == "layer_roads":
        order_clause = 'COALESCE(length_m, 0) DESC, "road_id"'
    else:
        order_clause = f'"{id_col}"'

    where_sql = " AND ".join(clauses)
    cols_sql = ", ".join([f'"{c}"' for c in [id_col] + prop_cols])

    sql = text(f"""
        SELECT {cols_sql}, ST_AsGeoJSON(geom) as geojson
        FROM {table_name}
        WHERE {where_sql}
        ORDER BY {order_clause}
        LIMIT :limit OFFSET :offset;
    """)

    rows = db.execute(sql, params).fetchall()
    features = []
    for r in rows:
        feat_id = str(r[0])
        props = {prop_cols[i]: r[i + 1] for i in range(len(prop_cols))}
        geom_json = json.loads(r[-1]) if r[-1] else {}
        features.append(
            FeatureItem(
                id=feat_id,
                layer_id=layer_id,
                properties=props,
                geometry=geom_json,
            )
        )
    return features


def get_feature_by_id(db: Session, layer_id: str, feature_id: str) -> FeatureItem:
    table_map = {
        "layer_admin": ("public.base_admin_boundary", "admin_id", ["name", "admin_level", "area_km2"]),
        "layer_buildings": ("public.osm_buildings", "building_id", ["name", "building", "height", "levels", "height_m", "height_source", "area_m2", "volume_m3"]),
        "layer_roads": ("public.osm_roads", "road_id", ["name", "highway", "length_m"]),
        "layer_water": ("public.osm_water", "water_id", ["name", "water_type", "natural_type", "waterway"]),
        "layer_green": ("public.osm_green", "green_id", ["name", "leisure", "landuse"]),
    }
    if layer_id not in table_map:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Layer '{layer_id}' not found",
        )

    table_name, id_col, prop_cols = table_map[layer_id]
    cols_sql = ", ".join([f'"{c}"' for c in [id_col] + prop_cols])
    sql = text(f"""
        SELECT {cols_sql}, ST_AsGeoJSON(geom) as geojson
        FROM {table_name}
        WHERE "{id_col}" = :feat_id
        LIMIT 1;
    """)
    r = db.execute(sql, {"feat_id": feature_id}).fetchone()
    if not r:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Feature '{feature_id}' not found in layer '{layer_id}'",
        )

    props = {prop_cols[i]: r[i + 1] for i in range(len(prop_cols))}
    geom_json = json.loads(r[-1]) if r[-1] else {}
    return FeatureItem(
        id=str(r[0]),
        layer_id=layer_id,
        properties=props,
        geometry=geom_json,
    )
