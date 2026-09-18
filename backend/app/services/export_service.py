"""Export generation service with UTF-8-SIG and CSV formula injection protection."""
import csv
import datetime
import hashlib
import json
import os
import uuid
from typing import Any, Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.config import settings
from app.db.models import ExportRecord, SystemTask, UgcCheckIn, User, WeatherRecord, utc_now
from app.schemas.export import CreateExportRequest, ExportStatusResponse
from app.services.env_service import get_fixed_view


def sanitize_csv_value(val: Any) -> str:
    """Protect against spreadsheet formula injection by escaping leading '=', '+', '-', '@'."""
    if val is None:
        return ""
    s = str(val)
    if s and s[0] in ("=", "+", "-", "@"):
        return f"'{s}"
    return s


def create_export_job(
    db: Session,
    user: User,
    req: CreateExportRequest,
    idempotency_key: str,
) -> tuple[ExportRecord, SystemTask]:
    now = utc_now()
    task_id = f"task_{uuid.uuid4().hex[:12]}"
    export_id = f"exp_{uuid.uuid4().hex[:12]}"

    # Ensure export storage directory exists
    os.makedirs(settings.EXPORT_STORAGE_DIR, exist_ok=True)
    ext = "csv" if req.file_format == "csv" else "geojson"
    file_path = str(settings.EXPORT_STORAGE_DIR / f"{export_id}.{ext}")

    task = SystemTask(
        id=task_id,
        task_type="export",
        owner_id=user.id,
        status="queued",
        progress_pct=0.0,
        created_at=now,
        updated_at=now,
    )
    db.add(task)
    db.flush()

    export_rec = ExportRecord(
        id=export_id,
        task_id=task_id,
        owner_id=user.id,
        export_type=req.export_type,
        file_format=req.file_format,
        file_path=file_path,
        file_size_bytes=0,
        status="processing",
        created_at=now,
        expires_at=now + datetime.timedelta(hours=24),
    )
    db.add(export_rec)
    db.commit()
    db.refresh(task)
    db.refresh(export_rec)

    return export_rec, task


def process_export_task(db: Session, export_id: str, req_params: dict):
    """Background task to generate export file and update status."""
    export_rec = db.query(ExportRecord).filter(ExportRecord.id == export_id).first()
    if not export_rec:
        return
    task = db.query(SystemTask).filter(SystemTask.id == export_rec.task_id).first()

    try:
        task.status = "running"
        task.progress_pct = 10.0
        db.commit()

        export_type = export_rec.export_type
        file_format = export_rec.file_format
        target_path = export_rec.file_path

        if export_type == "environment_table":
            view_id = req_params.get("view_id")
            if not view_id:
                raise ValueError("view_id is required for environment_table export")
            if view_id.startswith("sp_"):
                from app.services import spatial_service as spatial
                sp_view = spatial.read_view(view_id)
                with open(target_path, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f)
                    writer.writerow(["view_id", "target_time_utc", "variable", "unit", "availability", "release_id"])
                    for item in sp_view.get("items", []):
                        writer.writerow([
                            view_id,
                            sp_view.get("requested_time"),
                            item.get("variable"),
                            item.get("unit"),
                            item.get("availability"),
                            item.get("release_id"),
                        ])
            else:
                view = get_fixed_view(db, view_id)
                release_id = view.pinned_releases[0] if view.pinned_releases else None
                records = (
                    db.query(WeatherRecord)
                    .filter(WeatherRecord.release_id == release_id)
                    .order_by(WeatherRecord.target_time.asc())
                    .limit(10000)
                    .all()
                )

                # Write UTF-8-SIG CSV
                with open(target_path, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        "target_time_utc", "longitude", "latitude",
                        "air_temperature_c", "relative_humidity_pct",
                        "wind_speed_ms", "wind_direction_deg",
                        "shortwave_radiation_wm2", "direct_radiation_wm2",
                        "diffuse_radiation_wm2", "direct_normal_irradiance_wm2",
                    ])
                    for r in records:
                        writer.writerow([
                            r.target_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            r.lon,
                            r.lat,
                            sanitize_csv_value(r.temperature_2m),
                            sanitize_csv_value(r.relative_humidity_2m),
                            sanitize_csv_value(r.wind_speed_10m),
                            sanitize_csv_value(r.wind_direction_10m),
                            sanitize_csv_value(r.shortwave_radiation),
                            sanitize_csv_value(r.direct_radiation),
                            sanitize_csv_value(r.diffuse_radiation),
                            sanitize_csv_value(r.direct_normal_irradiance),
                        ])
        elif export_type == "my_check_ins":
            user_id = export_rec.owner_id
            items = (
                db.query(UgcCheckIn)
                .filter(UgcCheckIn.owner_id == user_id, UgcCheckIn.is_deleted.is_(False))
                .order_by(UgcCheckIn.created_at.desc())
                .all()
            )

            if file_format == "geojson":
                features = []
                for item in items:
                    features.append({
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [item.exact_lon, item.exact_lat]},
                        "properties": {
                            "check_in_id": item.id,
                            "experienced_at": item.experienced_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "thermal_sensation": item.thermal_sensation,
                            "thermal_comfort": item.thermal_comfort,
                            "setting": item.setting,
                            "activity": item.activity,
                            "sun_exposure": item.sun_exposure,
                            "note": item.note,
                            "visibility": item.visibility,
                            "match_status": item.match_status,
                            "matched_temperature": item.matched_temperature,
                        },
                    })
                with open(target_path, "w", encoding="utf-8") as f:
                    json.dump({"type": "FeatureCollection", "features": features}, f, ensure_ascii=False, indent=2)
            else:
                with open(target_path, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        "check_in_id", "experienced_at_utc", "exact_lon", "exact_lat",
                        "thermal_sensation", "thermal_comfort", "setting", "activity",
                        "sun_exposure", "note", "visibility", "match_status", "matched_temperature_c",
                    ])
                    for item in items:
                        writer.writerow([
                            item.id,
                            item.experienced_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            item.exact_lon,
                            item.exact_lat,
                            item.thermal_sensation,
                            item.thermal_comfort or "",
                            item.setting,
                            sanitize_csv_value(item.activity),
                            sanitize_csv_value(item.sun_exposure),
                            sanitize_csv_value(item.note),
                            item.visibility,
                            item.match_status,
                            item.matched_temperature or "",
                        ])

        elif export_type == "public_check_ins":
            items = (
                db.query(UgcCheckIn)
                .filter(
                    UgcCheckIn.visibility == "public",
                    UgcCheckIn.publication_status == "published",
                    UgcCheckIn.is_deleted.is_(False),
                )
                .order_by(UgcCheckIn.created_at.desc())
                .limit(10000)
                .all()
            )

            with open(target_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "check_in_id", "experienced_at_utc", "coarse_lon", "coarse_lat",
                    "public_precision", "thermal_sensation", "thermal_comfort",
                    "setting", "activity", "sun_exposure", "note",
                ])
                for item in items:
                    writer.writerow([
                        item.id,
                        item.experienced_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        item.coarse_lon,
                        item.coarse_lat,
                        item.public_location_precision,
                        item.thermal_sensation,
                        item.thermal_comfort or "",
                        item.setting,
                        sanitize_csv_value(item.activity),
                        sanitize_csv_value(item.sun_exposure),
                        sanitize_csv_value(item.note),
                    ])

        # Compute hash & size
        file_size = os.path.getsize(target_path)
        hasher = hashlib.sha256()
        with open(target_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        sha256 = hasher.hexdigest()

        export_rec.file_size_bytes = file_size
        export_rec.sha256_hash = sha256
        export_rec.status = "ready"

        task.status = "success"
        task.progress_pct = 100.0
        task.result_meta = {"file_size": file_size, "sha256": sha256}
        db.commit()

    except Exception as e:
        db.rollback()
        export_rec.status = "failed"
        task.status = "failed"
        task.error_message = str(e)
        db.commit()


def get_export_status(db: Session, export_id: str, user: User) -> ExportStatusResponse:
    rec = db.query(ExportRecord).filter(ExportRecord.id == export_id).first()
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export not found")

    if rec.owner_id != user.id and user.role != "admin":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export not found")

    download_url = None
    if rec.status == "ready":
        download_url = f"{settings.API_V1_PREFIX}/exports/{rec.id}/download"

    return ExportStatusResponse(
        export_id=rec.id,
        task_id=rec.task_id,
        export_type=rec.export_type,
        file_format=rec.file_format,
        status=rec.status,
        file_size_bytes=rec.file_size_bytes,
        download_url=download_url,
        sha256_hash=rec.sha256_hash,
        expires_at=rec.expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
