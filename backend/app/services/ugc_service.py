"""UGC check-in, privacy coarsening, matching, and aggregation services."""
import datetime
import hashlib
import json
import math
import uuid
import pyproj
from typing import Any, Optional
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.config import settings
from app.db.models import UgcCheckIn, UgcReport, User, WeatherRecord, EnvRelease, utc_now
from app.schemas.check_in import (
    CheckInAggregateItem,
    CheckInCreateRequest,
    CheckInOwnerItem,
    CheckInPublicItem,
    CheckInUpdateRequest,
    GeoPoint,
    MatchedEnvironment,
)
from app.services.env_service import is_inside_shanghai, parse_rfc3339_utc
from app.services.weather_service import configured_product_id

# Pre-initialize projections
TRANS_WGS84_TO_UTM51N = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32651", always_xy=True)
TRANS_UTM51N_TO_WGS84 = pyproj.Transformer.from_crs("EPSG:32651", "EPSG:4326", always_xy=True)

VALID_SENSATIONS = {"cold", "cool", "neutral", "warm", "hot"}
VALID_COMFORTS = {"comfortable", "ordinary", "uncomfortable"}
VALID_SETTINGS = {"indoor", "outdoor", "mixed", "unknown"}


def compute_coarse_200m_point(lon: float, lat: float) -> tuple[float, float]:
    """Snap point to center of 200m grid cell in EPSG:32651 and project back to WGS84."""
    x, y = TRANS_WGS84_TO_UTM51N.transform(lon, lat)
    cx = (math.floor(x / 200.0) + 0.5) * 200.0
    cy = (math.floor(y / 200.0) + 0.5) * 200.0
    c_lon, c_lat = TRANS_UTM51N_TO_WGS84.transform(cx, cy)
    return round(c_lon, 6), round(c_lat, 6)


def match_checkin_environment(db: Session, check_in_id: str, revision: int):
    """Asynchronous background worker to pair check-in with weather record."""
    item = db.query(UgcCheckIn).filter(UgcCheckIn.id == check_in_id).first()
    if not item or item.is_deleted:
        return
    # Abandon if a newer revision has already superseded this task
    if item.revision != revision:
        return

    # Find nearest weather record by time and location
    target_dt = item.experienced_at
    nearest_record = (
        db.query(WeatherRecord)
        .join(EnvRelease, WeatherRecord.release_id == EnvRelease.id)
        .filter(EnvRelease.scene_id == item.scene_id, EnvRelease.product_id == configured_product_id())
        .order_by(text(f"ABS(EXTRACT(EPOCH FROM (target_time - '{target_dt.isoformat()}')))") )
        .first()
    )

    if nearest_record:
        # Check time diff (< 3 hours)
        diff_sec = abs((nearest_record.target_time - target_dt).total_seconds())
        if diff_sec <= 3 * 3600:
            item.matched_temperature = nearest_record.temperature_2m
            item.matched_humidity = nearest_record.relative_humidity_2m
            item.matched_wind_speed = nearest_record.wind_speed_10m
            item.matched_radiation = nearest_record.shortwave_radiation
            item.matched_release_id = nearest_record.release_id
            item.match_status = "matched"
        else:
            item.match_status = "unmatched"
    else:
        item.match_status = "unmatched"

    db.commit()


def create_check_in(
    db: Session,
    user: User,
    req: CheckInCreateRequest,
    idempotency_key: str,
) -> tuple[UgcCheckIn, bool]:
    """Create check-in with idempotency check, boundary validation, and grid coarsening."""
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Header 'Idempotency-Key' is required for creating check-ins",
        )

    # 1. Validate sensation & setting
    if req.thermal_sensation not in VALID_SENSATIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid thermal_sensation. Must be one of {list(VALID_SENSATIONS)}",
        )
    if req.thermal_comfort and req.thermal_comfort not in VALID_COMFORTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid thermal_comfort. Must be one of {list(VALID_COMFORTS)}",
        )
    if req.setting not in VALID_SETTINGS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid setting. Must be one of {list(VALID_SETTINGS)}",
        )

    # 2. Location boundary check
    lon, lat = req.location.coordinates[0], req.location.coordinates[1]
    if not is_inside_shanghai(lon, lat):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Coordinates outside allowed Shanghai scene boundary",
        )

    # 3. Experience time check (allow up to 5 min future tolerance)
    now = utc_now()
    exp_dt = req.experienced_at
    if exp_dt.tzinfo is None:
        exp_dt = exp_dt.replace(tzinfo=datetime.timezone.utc)
    if exp_dt > now + datetime.timedelta(minutes=5):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Experience time in the future beyond 5 minutes tolerance is rejected",
        )

    # 4. Idempotency verification
    req_json = req.model_dump_json()
    req_hash = hashlib.sha256(req_json.encode("utf-8")).hexdigest()

    existing = (
        db.query(UgcCheckIn)
        .filter(
            UgcCheckIn.owner_id == user.id,
            UgcCheckIn.idempotency_key == idempotency_key,
        )
        .first()
    )
    if existing:
        if existing.request_hash == req_hash:
            return existing, False  # Already created
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency key reuse with differing payload",
            )

    # 5. Coarsening calculation
    if req.public_location_precision == "exact":
        c_lon, c_lat = lon, lat
    else:
        c_lon, c_lat = compute_coarse_200m_point(lon, lat)

    chk_id = f"chk_{uuid.uuid4().hex[:12]}"
    check_in = UgcCheckIn(
        id=chk_id,
        scene_id=req.scene_id,
        owner_id=user.id,
        idempotency_key=idempotency_key,
        request_hash=req_hash,
        exact_lon=lon,
        exact_lat=lat,
        coarse_lon=c_lon,
        coarse_lat=c_lat,
        public_location_precision=req.public_location_precision,
        location_source=req.location_source,
        horizontal_accuracy_m=req.horizontal_accuracy_m,
        experienced_at=exp_dt,
        time_source=req.time_source,
        time_uncertainty_minutes=req.time_uncertainty_minutes,
        thermal_sensation=req.thermal_sensation,
        thermal_comfort=req.thermal_comfort,
        setting=req.setting,
        activity=req.activity,
        sun_exposure=req.sun_exposure,
        note=req.note,
        visibility=req.visibility,
        publication_status="published" if req.visibility == "public" else "pending",
        revision=1,
        match_status="pending",
        created_at=now,
        updated_at=now,
    )
    db.add(check_in)
    db.commit()
    db.refresh(check_in)

    return check_in, True


def get_check_in_by_id(db: Session, check_in_id: str, current_user: Optional[User] = None):
    item = db.query(UgcCheckIn).filter(UgcCheckIn.id == check_in_id, UgcCheckIn.is_deleted.is_(False)).first()
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Check-in record not found",
        )

    # If owner or admin: return full owner projection
    if current_user and (current_user.id == item.owner_id or current_user.role == "admin"):
        matched_env = None
        if item.matched_release_id:
            matched_env = MatchedEnvironment(
                temperature_2m=item.matched_temperature,
                relative_humidity_2m=item.matched_humidity,
                wind_speed_10m=item.matched_wind_speed,
                shortwave_radiation=item.matched_radiation,
                release_id=item.matched_release_id,
            )
        return CheckInOwnerItem(
            id=item.id,
            scene_id=item.scene_id,
            owner_id=item.owner_id,
            exact_location=GeoPoint(coordinates=[item.exact_lon, item.exact_lat]),
            public_location=GeoPoint(coordinates=[item.coarse_lon, item.coarse_lat]),
            public_location_precision=item.public_location_precision,
            location_source=item.location_source,
            horizontal_accuracy_m=item.horizontal_accuracy_m,
            experienced_at=item.experienced_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            time_source=item.time_source,
            time_uncertainty_minutes=item.time_uncertainty_minutes,
            thermal_sensation=item.thermal_sensation,
            thermal_comfort=item.thermal_comfort,
            setting=item.setting,
            activity=item.activity,
            sun_exposure=item.sun_exposure,
            note=item.note,
            visibility=item.visibility,
            publication_status=item.publication_status,
            revision=item.revision,
            match_status=item.match_status,
            matched_environment=matched_env,
            created_at=item.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            updated_at=item.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    # Otherwise must be public and published
    if item.visibility != "public" or item.publication_status != "published":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Check-in record not found",
        )

    return CheckInPublicItem(
        id=item.id,
        scene_id=item.scene_id,
        location=GeoPoint(coordinates=[item.coarse_lon, item.coarse_lat]),
        public_location_precision=item.public_location_precision,
        experienced_at=item.experienced_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        thermal_sensation=item.thermal_sensation,
        thermal_comfort=item.thermal_comfort,
        setting=item.setting,
        activity=item.activity,
        sun_exposure=item.sun_exposure,
        note=item.note,
        created_at=item.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def list_public_check_ins(
    db: Session,
    scene_id: str,
    bbox: list[float],
    start_time: str,
    end_time: str,
    limit: int = 50,
    offset: int = 0,
) -> list[CheckInPublicItem]:
    limit = min(max(1, limit), 200)
    dt_start = parse_rfc3339_utc(start_time)
    dt_end = parse_rfc3339_utc(end_time)

    items = (
        db.query(UgcCheckIn)
        .filter(
            UgcCheckIn.scene_id == scene_id,
            UgcCheckIn.visibility == "public",
            UgcCheckIn.publication_status == "published",
            UgcCheckIn.is_deleted.is_(False),
            UgcCheckIn.coarse_lon >= bbox[0],
            UgcCheckIn.coarse_lat >= bbox[1],
            UgcCheckIn.coarse_lon <= bbox[2],
            UgcCheckIn.coarse_lat <= bbox[3],
            UgcCheckIn.experienced_at >= dt_start,
            UgcCheckIn.experienced_at < dt_end,
        )
        .order_by(UgcCheckIn.experienced_at.desc(), UgcCheckIn.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        CheckInPublicItem(
            id=i.id,
            scene_id=i.scene_id,
            location=GeoPoint(coordinates=[i.coarse_lon, i.coarse_lat]),
            public_location_precision=i.public_location_precision,
            experienced_at=i.experienced_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            thermal_sensation=i.thermal_sensation,
            thermal_comfort=i.thermal_comfort,
            setting=i.setting,
            activity=i.activity,
            sun_exposure=i.sun_exposure,
            note=i.note,
            created_at=i.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        for i in items
    ]


def list_my_check_ins(
    db: Session,
    user: User,
    limit: int = 50,
    offset: int = 0,
) -> list[CheckInOwnerItem]:
    limit = min(max(1, limit), 200)
    items = (
        db.query(UgcCheckIn)
        .filter(
            UgcCheckIn.owner_id == user.id,
            UgcCheckIn.is_deleted.is_(False),
        )
        .order_by(UgcCheckIn.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    res = []
    for item in items:
        matched_env = None
        if item.matched_release_id:
            matched_env = MatchedEnvironment(
                temperature_2m=item.matched_temperature,
                relative_humidity_2m=item.matched_humidity,
                wind_speed_10m=item.matched_wind_speed,
                shortwave_radiation=item.matched_radiation,
                release_id=item.matched_release_id,
            )
        res.append(
            CheckInOwnerItem(
                id=item.id,
                scene_id=item.scene_id,
                owner_id=item.owner_id,
                exact_location=GeoPoint(coordinates=[item.exact_lon, item.exact_lat]),
                public_location=GeoPoint(coordinates=[item.coarse_lon, item.coarse_lat]),
                public_location_precision=item.public_location_precision,
                location_source=item.location_source,
                horizontal_accuracy_m=item.horizontal_accuracy_m,
                experienced_at=item.experienced_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                time_source=item.time_source,
                time_uncertainty_minutes=item.time_uncertainty_minutes,
                thermal_sensation=item.thermal_sensation,
                thermal_comfort=item.thermal_comfort,
                setting=item.setting,
                activity=item.activity,
                sun_exposure=item.sun_exposure,
                note=item.note,
                visibility=item.visibility,
                publication_status=item.publication_status,
                revision=item.revision,
                match_status=item.match_status,
                matched_environment=matched_env,
                created_at=item.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                updated_at=item.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        )
    return res


def update_check_in(
    db: Session,
    user: User,
    check_in_id: str,
    req: CheckInUpdateRequest,
    if_match: Optional[str],
) -> UgcCheckIn:
    if not if_match:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="Header 'If-Match' with current revision is required for modifying records",
        )

    item = db.query(UgcCheckIn).filter(UgcCheckIn.id == check_in_id, UgcCheckIn.is_deleted.is_(False)).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")

    if item.owner_id != user.id and user.role != "admin":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")

    # Match revision
    if if_match.strip('"') != str(item.revision):
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail=f"Revision conflict. Server revision is {item.revision}",
        )

    # Apply updates
    if req.thermal_sensation is not None:
        if req.thermal_sensation not in VALID_SENSATIONS:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid sensation")
        item.thermal_sensation = req.thermal_sensation

    if req.thermal_comfort is not None:
        if req.thermal_comfort not in VALID_COMFORTS:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid comfort")
        item.thermal_comfort = req.thermal_comfort

    if req.setting is not None:
        if req.setting not in VALID_SETTINGS:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid setting")
        item.setting = req.setting

    if req.activity is not None:
        item.activity = req.activity
    if req.sun_exposure is not None:
        item.sun_exposure = req.sun_exposure
    if req.note is not None:
        item.note = req.note

    if req.visibility is not None:
        item.visibility = req.visibility
        item.publication_status = "published" if req.visibility == "public" else "pending"

    if req.public_location_precision is not None:
        item.public_location_precision = req.public_location_precision
        if req.public_location_precision == "exact":
            item.coarse_lon, item.coarse_lat = item.exact_lon, item.exact_lat
        else:
            item.coarse_lon, item.coarse_lat = compute_coarse_200m_point(item.exact_lon, item.exact_lat)

    item.revision += 1
    item.updated_at = utc_now()
    db.commit()
    db.refresh(item)
    return item


def delete_check_in(
    db: Session,
    user: User,
    check_in_id: str,
    if_match: Optional[str],
):
    if not if_match:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="Header 'If-Match' with current revision is required for deleting records",
        )

    item = db.query(UgcCheckIn).filter(UgcCheckIn.id == check_in_id, UgcCheckIn.is_deleted.is_(False)).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")

    if item.owner_id != user.id and user.role != "admin":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")

    if if_match.strip('"') != str(item.revision):
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail=f"Revision conflict. Server revision is {item.revision}",
        )

    item.is_deleted = True
    item.updated_at = utc_now()
    db.commit()


def aggregate_check_ins(
    db: Session,
    scene_id: str,
    bbox: list[float],
    start_time: str,
    end_time: str,
) -> list[CheckInAggregateItem]:
    dt_start = parse_rfc3339_utc(start_time)
    dt_end = parse_rfc3339_utc(end_time)

    # Aggregate by coarse coordinates
    items = (
        db.query(
            UgcCheckIn.coarse_lon,
            UgcCheckIn.coarse_lat,
            UgcCheckIn.thermal_sensation,
            func.count(UgcCheckIn.id).label("cnt"),
        )
        .filter(
            UgcCheckIn.scene_id == scene_id,
            UgcCheckIn.visibility == "public",
            UgcCheckIn.publication_status == "published",
            UgcCheckIn.is_deleted.is_(False),
            UgcCheckIn.coarse_lon >= bbox[0],
            UgcCheckIn.coarse_lat >= bbox[1],
            UgcCheckIn.coarse_lon <= bbox[2],
            UgcCheckIn.coarse_lat <= bbox[3],
            UgcCheckIn.experienced_at >= dt_start,
            UgcCheckIn.experienced_at < dt_end,
        )
        .group_by(UgcCheckIn.coarse_lon, UgcCheckIn.coarse_lat, UgcCheckIn.thermal_sensation)
        .all()
    )

    # Group into cells
    cells: dict[tuple[float, float], dict[str, Any]] = {}
    for lon, lat, sens, count in items:
        key = (round(lon, 6), round(lat, 6))
        if key not in cells:
            cells[key] = {
                "total": 0,
                "sensation": {"cold": 0, "cool": 0, "neutral": 0, "warm": 0, "hot": 0},
            }
        cells[key]["total"] += count
        if sens in cells[key]["sensation"]:
            cells[key]["sensation"][sens] += count

    aggregates = []
    for (lon, lat), info in cells.items():
        grid_id = f"grid_{int(lon*1000)}_{int(lat*1000)}"
        aggregates.append(
            CheckInAggregateItem(
                grid_id=grid_id,
                center_lon=lon,
                center_lat=lat,
                total_count=info["total"],
                sensation_counts=info["sensation"],
            )
        )
    return aggregates


def report_check_in(
    db: Session,
    user: User,
    check_in_id: str,
    reason: str,
    idempotency_key: str,
):
    item = db.query(UgcCheckIn).filter(UgcCheckIn.id == check_in_id, UgcCheckIn.is_deleted.is_(False)).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")

    existing = (
        db.query(UgcReport)
        .filter(UgcReport.reporter_id == user.id, UgcReport.idempotency_key == idempotency_key)
        .first()
    )
    if existing:
        return existing

    rep = UgcReport(
        check_in_id=check_in_id,
        reporter_id=user.id,
        idempotency_key=idempotency_key,
        reason=reason,
        status="pending",
    )
    db.add(rep)
    db.commit()
    db.refresh(rep)
    return rep
