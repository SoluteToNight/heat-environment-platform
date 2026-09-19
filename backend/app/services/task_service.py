"""System tasks and scene operational status service."""
import hashlib
from typing import Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.db.models import EnvRelease, SystemTask, User, utc_now
from app.schemas.task import SceneStatusResponse, TaskResponse
from app.services.weather_service import configured_product_id
from app.schemas.common import format_utc_z


def get_scene_status_info(db: Session, scene_id: str) -> tuple[SceneStatusResponse, str]:
    """Return scene operational status along with ETag for condition caching."""
    now = utc_now()
    latest_rel = (
        db.query(EnvRelease)
        .filter(EnvRelease.scene_id == scene_id, EnvRelease.product_id == configured_product_id())
        .order_by(EnvRelease.computed_at.desc())
        .first()
    )

    running_task = (
        db.query(SystemTask)
        .filter(SystemTask.task_type == "weather_sync", SystemTask.status == "running")
        .first()
    )
    update_state = "running" if running_task else "idle"

    freshness = "unknown"
    last_success_str = None
    active_releases = []

    if latest_rel:
        age_hours = (now - latest_rel.computed_at).total_seconds() / 3600.0
        freshness = "fresh" if age_hours <= 3.0 else "stale"
        last_success_str = format_utc_z(latest_rel.computed_at)
        active_releases = [latest_rel.id]

    etag_raw = f"{scene_id}_{update_state}_{freshness}_{last_success_str}"
    etag = f'"{hashlib.md5(etag_raw.encode("utf-8")).hexdigest()}"'

    resp = SceneStatusResponse(
        scene_id=scene_id,
        update_state=update_state,
        freshness=freshness,
        last_success_at=last_success_str,
        active_releases=active_releases,
        reason_code=None,
    )
    return resp, etag


def get_task_by_id(db: Session, task_id: str, user: User) -> TaskResponse:
    task = db.query(SystemTask).filter(SystemTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    # Access control: creator or admin
    if task.owner_id and task.owner_id != user.id and user.role != "admin":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    return TaskResponse(
        task_id=task.id,
        task_type=task.task_type,
        status=task.status,
        progress_pct=task.progress_pct,
        error_message=task.error_message,
        result_meta=task.result_meta,
        created_at=format_utc_z(task.created_at),
        updated_at=format_utc_z(task.updated_at),
    )
