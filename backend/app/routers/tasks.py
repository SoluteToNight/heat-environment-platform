"""System tasks and scene status router."""
from typing import Optional
from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import make_api_response
from app.services.auth_service import get_current_user
from app.services.task_service import get_scene_status_info, get_task_by_id
from app.services import spatial_service as spatial
import datetime

router = APIRouter(tags=["A05 状态与任务"])


@router.get("/scenes/{scene_id}/status")
def get_scene_status(
    scene_id: str,
    response: Response,
    request: Request,
    if_none_match: Optional[str] = Header(None, alias="If-None-Match"),
    db: Session = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_scene_status")
    published = spatial.published_products() if scene_id == 'scene_shanghai' else {}
    if published:
        import hashlib, json
        releases = sorted({manifest['run_id'] for manifest in published.values()})
        fresh = all((spatial.utc_now() - datetime.datetime.fromisoformat(manifest['created_at'])).total_seconds() <= 10800 for manifest in published.values())
        payload = {
            'scene_id': scene_id,
            'release_ids': releases,
            'freshness': 'fresh' if fresh else 'stale',
            'update_state': 'running' if (spatial.settings.SPATIAL_STORAGE_DIR / '.publish-lock').exists() else 'idle'
        }
        etag = f'"{hashlib.md5(json.dumps(payload, sort_keys=True).encode()).hexdigest()}"'
        response.headers["ETag"] = etag
        if if_none_match and if_none_match == etag:
            return Response(status_code=status.HTTP_304_NOT_MODIFIED)
        return make_api_response(payload, request_id)
    status_info, etag = get_scene_status_info(db, scene_id)

    response.headers["ETag"] = etag
    if if_none_match and if_none_match == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED)

    return make_api_response(status_info.model_dump(), request_id)


@router.get("/tasks/{task_id}")
def get_task(
    task_id: str,
    request: Request,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_task_detail")
    task_info = get_task_by_id(db, task_id, current_user)
    return make_api_response(task_info.model_dump(), request_id)
