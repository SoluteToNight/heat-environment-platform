"""Data export request and file download router."""
import os
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.models import ExportRecord, utc_now
from app.db.session import get_db
from app.schemas.common import format_utc_z, make_api_response
from app.schemas.export import CreateExportRequest
from app.services.auth_service import get_current_user
from app.services.export_service import create_export_job, get_export_status, process_export_task

router = APIRouter(prefix="/exports", tags=["A06 导出"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def post_export(
    req: CreateExportRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_post_export")
    if req.export_type not in ("environment_table", "my_check_ins", "public_check_ins"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid export_type. Must be 'environment_table', 'my_check_ins', or 'public_check_ins'",
        )

    export_rec, task = create_export_job(db, current_user, req, idempotency_key)
    background_tasks.add_task(process_export_task, db, export_rec.id, req.model_dump())

    return make_api_response(
        {
            "export_id": export_rec.id,
            "task_id": task.id,
            "status": export_rec.status,
            "export_type": export_rec.export_type,
            "file_format": export_rec.file_format,
            "expires_at": format_utc_z(export_rec.expires_at),
        },
        request_id,
    )


@router.get("/{export_id}")
def get_export(
    export_id: str,
    request: Request,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_export_detail")
    status_resp = get_export_status(db, export_id, current_user)
    return make_api_response(status_resp.model_dump(), request_id)


@router.get("/{export_id}/download")
def download_export_file(
    export_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rec = db.query(ExportRecord).filter(ExportRecord.id == export_id).first()
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export not found")

    if rec.owner_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export not found")

    if rec.status != "ready" or not os.path.exists(rec.file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Export file is not ready or has been removed",
        )

    if rec.expires_at < utc_now():
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Export file has expired")

    media_type = "text/csv; charset=utf-8" if rec.file_format == "csv" else "application/geo+json"
    filename = f"{rec.export_type}_{export_id}.{rec.file_format}"
    return FileResponse(
        path=rec.file_path,
        media_type=media_type,
        filename=filename,
    )
