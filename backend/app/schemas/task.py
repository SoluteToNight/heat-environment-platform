"""Schemas for system tasks and scene status."""
from typing import Any, Optional
from pydantic import BaseModel


class SceneStatusResponse(BaseModel):
    scene_id: str
    update_state: str  # idle, queued, running, failed
    freshness: str  # fresh, stale, unknown
    last_success_at: Optional[str] = None
    active_releases: list[str] = []
    reason_code: Optional[str] = None


class TaskResponse(BaseModel):
    task_id: str
    task_type: str
    status: str  # queued, running, success, failed, cancelled
    progress_pct: Optional[float] = None
    error_message: Optional[str] = None
    result_meta: Optional[dict[str, Any]] = None
    created_at: str
    updated_at: str
