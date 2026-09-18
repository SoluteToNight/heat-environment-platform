"""Environment exploration, catalog, releases, views, and point/series query services."""
import datetime
import math
import os
import uuid
from pathlib import Path
from typing import Any, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
import pyproj
import rasterio

# Fix PROJ_DATA if needed
try:
    os.environ['PROJ_DATA'] = pyproj.datadir.get_data_dir()
    os.environ['PROJ_LIB'] = pyproj.datadir.get_data_dir()
except Exception:
    pass

# 用户明确指示：去掉 DEM 的高程基准，因为该 12.5m DEM 未剔除建筑物高度（实为 DSM 表面模型）。
# 在未经地面滤波点云剥离前，不能作为平原地面真实高程基准，避免将建筑物高度误作地表海拔。
def sample_dem_at(lon: float, lat: float) -> tuple[Optional[float], Optional[float]]:
    return None, None

from app.config import settings
from app.db.models import EnvRelease, EnvView, WeatherRecord, utc_now
from app.schemas.environment import (
    CatalogVariable,
    CreateViewRequest,
    PointReading,
    PointResponse,
    ProductCatalog,
    ReleaseItem,
    SeriesResponse,
    SeriesTimeStep,
    ViewResponse,
    ViewVariableDetail,
)
from app.services.weather_service import PRODUCT_SPECS, configured_product_id, parse_rfc3339_utc, sync_weather_release


VARIABLE_DEFINITIONS = {
    "air_temperature": {
        "name": "近地 2 米气温",
        "unit": "°C",
        "col": "temperature_2m",
        "desc": "离地 2 米高度环境干球空气温度",
    },
    "relative_humidity": {
        "name": "近地 2 米相对湿度",
        "unit": "%",
        "col": "relative_humidity_2m",
        "desc": "离地 2 米空气水汽压与饱和水汽压百分比",
    },
    "wind_speed": {
        "name": "离地 10 米风速",
        "unit": "m/s",
        "col": "wind_speed_10m",
        "desc": "离地 10 米高度标量风速",
    },
    "wind_direction": {
        "name": "离地 10 米风向",
        "unit": "°",
        "col": "wind_direction_10m",
        "desc": "离地 10 米来风方向，正北为 0°，顺时针",
    },
    "shortwave_radiation": {
        "name": "总短波辐照度 (GHI)",
        "unit": "W/m²",
        "col": "shortwave_radiation",
        "desc": "地表受到的半球总短波下行辐射通量密度",
    },
    "direct_radiation": {
        "name": "水平直射辐射",
        "unit": "W/m²",
        "col": "direct_radiation",
        "desc": "太阳直射光束在水平地面上的投影辐射",
    },
    "diffuse_radiation": {
        "name": "散射辐射",
        "unit": "W/m²",
        "col": "diffuse_radiation",
        "desc": "大气层散射后到达地表的短波辐射",
    },
    "direct_normal_irradiance": {
        "name": "法向直射辐射 (DNI)",
        "unit": "W/m²",
        "col": "direct_normal_irradiance",
        "desc": "垂直于太阳光束平面的直射辐照度",
    },
    "net_shortwave_background": {
        "name": "宏观净短波背景",
        "unit": "W/m²",
        "col": "shortwave_radiation",
        "desc": "区域尺度无建筑遮挡时的地表短波净吸收背景",
    },
    "local_downwelling_shortwave": {
        "name": "局地下行短波辐射",
        "unit": "W/m²",
        "col": None,
        "desc": "考虑微观三维建筑/树冠阴影遮挡后的局地可达短波辐射",
    },
}


def get_environment_catalog(scene_id: str) -> list[ProductCatalog]:
    catalogs = []
    for prod_id, info in PRODUCT_SPECS.items():
        if prod_id != configured_product_id():
            continue
        var_list = []
        for v_code, v_info in VARIABLE_DEFINITIONS.items():
            avail = "available"
            if v_code == "local_downwelling_shortwave":
                avail = "unsupported"
            if 'variables' in info and v_code not in info['variables']:
                avail = 'unsupported'
            var_list.append(
                CatalogVariable(
                    code=v_code,
                    name={'air_temperature': '气温', 'relative_humidity': '相对湿度', 'wind_speed': '风速', 'wind_direction': '风向'}.get(v_code, v_info['name']) if prod_id == 'qweather' else v_info["name"],
                    unit=v_info["unit"],
                    description='和风逐小时预报；接口未声明接收高度，单个请求位置不代表全市空间分布。' if prod_id == 'qweather' and v_code in info['variables'] else v_info["desc"],
                    availability=avail,
                )
            )
        catalogs.append(
            ProductCatalog(
                product_id=prod_id,
                name=info["title"],
                model_source=info["source"],
                description="JWT 认证的单位置逐小时天气预报" if prod_id == 'qweather' else "开放无需认证的气象预报与分析数据产品",
                variables=var_list,
            )
        )
    return catalogs


def list_scene_releases(db: Session, scene_id: str) -> list[ReleaseItem]:
    now = utc_now()
    releases = (
        db.query(EnvRelease)
        .filter(EnvRelease.scene_id == scene_id)
        .order_by(EnvRelease.computed_at.desc())
        .limit(20)
        .all()
    )
    items = []
    for r in releases:
        # Check freshness: fresh if computed within 3 hours
        age_hours = (now - r.computed_at).total_seconds() / 3600.0
        freshness = "fresh" if age_hours <= 3.0 else "stale"
        items.append(
            ReleaseItem(
                release_id=r.id,
                product_id=r.product_id,
                model_source=r.model_source,
                time_start=r.time_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                time_end=r.time_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                freshness=freshness,
                availability=r.availability,
            )
        )
    return items


def is_inside_shanghai(lon: float, lat: float) -> bool:
    b = settings.SHANGHAI_BBOX
    return b[0] <= lon <= b[2] and b[1] <= lat <= b[3]


def create_fixed_view(db: Session, req: CreateViewRequest) -> ViewResponse:
    now = utc_now()

    # 1. Resolve requested time
    if req.time_selection.kind == "now":
        requested_dt = now
    elif req.time_selection.kind == "at" and req.time_selection.time:
        requested_dt = parse_rfc3339_utc(req.time_selection.time)
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="time_selection must specify kind='now' or kind='at' with valid RFC 3339 time",
        )

    release: Optional[EnvRelease] = None
    if req.release_selection.mode == "pinned" and req.release_selection.release_ids:
        release = db.query(EnvRelease).filter(EnvRelease.id == req.release_selection.release_ids[0], EnvRelease.scene_id == req.scene_id).first()
        if release is None:
            raise HTTPException(status_code=404, detail='Pinned weather release not found in this scene.')
    else:
        release = (
            db.query(EnvRelease)
            .filter(EnvRelease.scene_id == req.scene_id, EnvRelease.product_id == configured_product_id())
            .order_by(EnvRelease.computed_at.desc())
            .first()
        )

    if req.release_selection.mode != 'pinned' and (not release or (now - release.computed_at).total_seconds() >= 3000):
        from app.services.qweather_service import QWeatherError
        try:
            release = sync_weather_release(db, scene_id=req.scene_id)
        except QWeatherError as error:
            db.rollback()
            if release is None:
                headers = {'Retry-After': error.retry_after} if error.retry_after else None
                raise HTTPException(status_code=503, detail=str(error), headers=headers) from None

    if release.product_id == 'qweather' and req.time_selection.kind == 'at' and not (release.time_start <= requested_dt <= release.time_end):
        raise HTTPException(status_code=422, detail='Requested time is outside this QWeather forecast release. Historical observations are not supplied by this endpoint.')

    # 3. Find closest hour in records
    nearest_record = (
        db.query(WeatherRecord)
        .filter(WeatherRecord.release_id == release.id)
        .order_by(text(f"ABS(EXTRACT(EPOCH FROM (target_time - '{requested_dt.isoformat()}')))") )
        .first()
    )

    resolved_dt = nearest_record.target_time if nearest_record else requested_dt

    # 4. Expiration: 24h
    expires_at = now + datetime.timedelta(hours=settings.VIEW_EXPIRE_HOURS)
    view_id = f"view_{uuid.uuid4().hex[:12]}"

    env_view = EnvView(
        id=view_id,
        scene_id=req.scene_id,
        requested_time=requested_dt,
        resolved_time=resolved_dt,
        time_selection_kind=req.time_selection.kind,
        release_selection_mode=req.release_selection.mode,
        variables=req.variables,
        pinned_releases=[release.id],
        created_at=now,
        expires_at=expires_at,
    )
    db.add(env_view)
    db.commit()
    db.refresh(env_view)

    # Build response variables
    var_details = []
    age_hours = (now - release.computed_at).total_seconds() / 3600.0
    freshness = "fresh" if age_hours <= 3.0 else "stale"

    for var_code in req.variables:
        v_def = VARIABLE_DEFINITIONS.get(var_code, {})
        avail = "available"
        reason = None
        if var_code == "local_downwelling_shortwave":
            avail = "unsupported"
            reason = "DSM_RAYTRACING_UNSUPPORTED"
        elif var_code not in VARIABLE_DEFINITIONS:
            avail = "missing"
            reason = "UNKNOWN_VARIABLE"
        elif release.product_id == 'qweather' and var_code not in PRODUCT_SPECS['qweather']['variables']:
            avail = 'unsupported'
            reason = 'QWEATHER_HOURLY_VARIABLE_UNAVAILABLE'
        elif nearest_record is None or getattr(nearest_record, v_def.get('col') or '', None) is None:
            avail = 'missing'
            reason = 'DATA_GAP'

        var_details.append(
            ViewVariableDetail(
                product_id=release.product_id,
                variable=var_code,
                release_id=release.id,
                unit=v_def.get("unit", "-"),
                availability=avail,
                freshness=freshness,
                reason_code=reason,
                provenance={
                    "model": release.model_source,
                    "resolution": (release.raw_meta or {}).get('spatial_support', 'Provider background forecast at a single requested location'),
                    "receiver_height": (release.raw_meta or {}).get('receiver_height'),
                    "temporal_support": (release.raw_meta or {}).get('temporal_support'),
                    "attributions": (release.raw_meta or {}).get('attributions', []),
                    "forecast_location": {'longitude': (release.raw_meta or {}).get('longitude'), 'latitude': (release.raw_meta or {}).get('latitude')},
                    "source_release_computed_at": release.computed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            )
        )

    return ViewResponse(
        view_id=env_view.id,
        scene_id=env_view.scene_id,
        requested_time=env_view.requested_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        resolved_time=env_view.resolved_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        variables=var_details,
        expires_at=env_view.expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def get_fixed_view(db: Session, view_id: str) -> EnvView:
    view = db.query(EnvView).filter(EnvView.id == view_id).first()
    if not view:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"View '{view_id}' not found",
        )
    if view.expires_at < utc_now():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="View has expired. Please create a new view snapshot.",
        )
    return view


def get_point_reading(db: Session, view_id: str, lon: float, lat: float) -> PointResponse:
    view = get_fixed_view(db, view_id)
    release_id = view.pinned_releases[0] if view.pinned_releases else None
    release = db.query(EnvRelease).filter(EnvRelease.id == release_id).first()

    # Check coverage
    in_bounds = is_inside_shanghai(lon, lat)

    # Query matching weather record
    record = (
        db.query(WeatherRecord)
        .filter(WeatherRecord.release_id == release_id, WeatherRecord.target_time == view.resolved_time)
        .first()
    )

    readings = []
    for var_code in view.variables:
        v_def = VARIABLE_DEFINITIONS.get(var_code)
        if not v_def:
            readings.append(
                PointReading(
                    variable=var_code,
                    value=None,
                    unit="-",
                    value_status="no_data",
                    reason_code="VARIABLE_NOT_CONFIGURED",
                )
            )
            continue

        if not in_bounds:
            readings.append(
                PointReading(
                    variable=var_code,
                    value=None,
                    unit=v_def["unit"],
                    value_status="outside_coverage",
                    reason_code="COORDINATE_OUTSIDE_SHANGHAI",
                )
            )
            continue

        if var_code == "local_downwelling_shortwave":
            readings.append(
                PointReading(
                    variable=var_code,
                    value=None,
                    unit=v_def["unit"],
                    value_status="unsupported",
                    reason_code="DSM_NOT_ENABLED",
                )
            )
            continue

        if release and release.product_id == 'qweather' and var_code not in PRODUCT_SPECS['qweather']['variables']:
            readings.append(PointReading(variable=var_code, value=None, unit=v_def['unit'], value_status='unsupported', reason_code='QWEATHER_HOURLY_VARIABLE_UNAVAILABLE'))
            continue

        if not record:
            readings.append(
                PointReading(
                    variable=var_code,
                    value=None,
                    unit=v_def["unit"],
                    value_status="no_data",
                    reason_code="TIMESTAMP_NOT_FOUND_IN_RELEASE",
                )
            )
            continue

        val = getattr(record, v_def["col"], None)
        readings.append(
            PointReading(
                variable=var_code,
                value=float(val) if val is not None else None,
                unit=v_def["unit"],
                value_status="valid" if val is not None else "no_data",
                reason_code=None if val is not None else "DATA_GAP",
            )
        )

    elevation_m, slope_deg = sample_dem_at(lon, lat) if in_bounds else (None, None)

    return PointResponse(
        view_id=view.id,
        lon=lon,
        lat=lat,
        target_time=view.resolved_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        readings=readings,
        elevation_m=elevation_m,
        slope_deg=slope_deg,
    )


def get_series_readings(
    db: Session,
    view_id: str,
    lon: float,
    lat: float,
    start_time: str,
    end_time: str,
    variables: Optional[list[str]] = None,
) -> SeriesResponse:
    view = get_fixed_view(db, view_id)
    release_id = view.pinned_releases[0] if view.pinned_releases else None
    release = db.query(EnvRelease).filter(EnvRelease.id == release_id).first()

    dt_start = parse_rfc3339_utc(start_time)
    dt_end = parse_rfc3339_utc(end_time)

    records = (
        db.query(WeatherRecord)
        .filter(
            WeatherRecord.release_id == release_id,
            WeatherRecord.target_time >= dt_start,
            WeatherRecord.target_time < dt_end,
        )
        .order_by(WeatherRecord.target_time.asc())
        .limit(240)
        .all()
    )

    query_vars = variables or view.variables
    in_bounds = is_inside_shanghai(lon, lat)

    steps = []
    for r in records:
        v_map = {}
        s_map = {}
        for var_code in query_vars:
            v_def = VARIABLE_DEFINITIONS.get(var_code)
            if not in_bounds:
                v_map[var_code] = None
                s_map[var_code] = "outside_coverage"
            elif var_code == "local_downwelling_shortwave":
                v_map[var_code] = None
                s_map[var_code] = "unsupported"
            elif release and release.product_id == 'qweather' and var_code not in PRODUCT_SPECS['qweather']['variables']:
                v_map[var_code] = None
                s_map[var_code] = 'unsupported'
            elif not v_def or not v_def["col"]:
                v_map[var_code] = None
                s_map[var_code] = "no_data"
            else:
                val = getattr(r, v_def["col"], None)
                v_map[var_code] = float(val) if val is not None else None
                s_map[var_code] = "valid" if val is not None else "no_data"

        steps.append(
            SeriesTimeStep(
                time=r.target_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                values=v_map,
                status=s_map,
            )
        )

    return SeriesResponse(
        view_id=view.id,
        lon=lon,
        lat=lat,
        steps=steps,
    )
