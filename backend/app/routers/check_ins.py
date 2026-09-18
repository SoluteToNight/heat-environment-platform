"""UGC check-in, aggregates, update, deletion, and reporting router."""
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.check_in import CheckInCreateRequest, CheckInUpdateRequest, ReportCreateRequest
from app.schemas.common import make_api_response
from app.services.auth_service import get_current_user, get_optional_current_user
from app.services.ugc_service import (
    aggregate_check_ins,
    create_check_in,
    delete_check_in,
    get_check_in_by_id,
    list_my_check_ins,
    list_public_check_ins,
    match_checkin_environment,
    report_check_in,
    update_check_in,
)

router = APIRouter(tags=["A03 UGC 管理"])


@router.post("/check-ins", status_code=status.HTTP_201_CREATED)
def post_check_in(
    req: CheckInCreateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_post_checkin")
    check_in, is_new = create_check_in(db, current_user, req, idempotency_key)

    # Trigger async environment pairing
    if is_new:
        background_tasks.add_task(match_checkin_environment, db, check_in.id, check_in.revision)

    # Return owner view
    resp_data = get_check_in_by_id(db, check_in.id, current_user=current_user)
    return make_api_response(resp_data.model_dump(), request_id)


@router.get("/check-ins")
def get_public_check_ins(
    request: Request,
    scene_id: str = Query(..., description="Scene ID"),
    bbox: str = Query(..., description="min_lon,min_lat,max_lon,max_lat"),
    start_time: str = Query(..., description="RFC 3339 start timestamp"),
    end_time: str = Query(..., description="RFC 3339 end timestamp"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_public_checkins")
    try:
        bbox_coords = [float(x.strip()) for x in bbox.split(",")]
        if len(bbox_coords) != 4:
            raise ValueError()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="bbox must be 'min_lon,min_lat,max_lon,max_lat'",
        )

    items = list_public_check_ins(
        db,
        scene_id=scene_id,
        bbox=bbox_coords,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
    )
    return make_api_response([i.model_dump() for i in items], request_id)


@router.get("/check-ins/aggregates")
def get_aggregates(
    request: Request,
    scene_id: str = Query(..., description="Scene ID"),
    bbox: str = Query(..., description="min_lon,min_lat,max_lon,max_lat"),
    start_time: str = Query(..., description="RFC 3339 start timestamp"),
    end_time: str = Query(..., description="RFC 3339 end timestamp"),
    db: Session = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_checkin_aggs")
    try:
        bbox_coords = [float(x.strip()) for x in bbox.split(",")]
        if len(bbox_coords) != 4:
            raise ValueError()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="bbox must be 'min_lon,min_lat,max_lon,max_lat'",
        )

    aggs = aggregate_check_ins(db, scene_id=scene_id, bbox=bbox_coords, start_time=start_time, end_time=end_time)
    return make_api_response([a.model_dump() for a in aggs], request_id)


@router.get("/me/check-ins")
def get_my_check_ins(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_my_checkins")
    items = list_my_check_ins(db, current_user, limit=limit, offset=offset)
    return make_api_response([i.model_dump() for i in items], request_id)


@router.get("/check-ins/{check_in_id}")
def get_check_in(
    check_in_id: str,
    request: Request,
    current_user=Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_checkin_detail")
    item = get_check_in_by_id(db, check_in_id, current_user=current_user)
    return make_api_response(item.model_dump(), request_id)


@router.patch("/check-ins/{check_in_id}")
def patch_check_in(
    check_in_id: str,
    req: CheckInUpdateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_patch_checkin")
    updated = update_check_in(db, current_user, check_in_id, req, if_match)
    background_tasks.add_task(match_checkin_environment, db, updated.id, updated.revision)
    item = get_check_in_by_id(db, updated.id, current_user=current_user)
    return make_api_response(item.model_dump(), request_id)


@router.delete("/check-ins/{check_in_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_check_in(
    check_in_id: str,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    delete_check_in(db, current_user, check_in_id, if_match)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/check-ins/{check_in_id}/reports", status_code=status.HTTP_201_CREATED)
def report_check_in_record(
    check_in_id: str,
    req: ReportCreateRequest,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_report_checkin")
    report = report_check_in(db, current_user, check_in_id, req.reason, idempotency_key)
    return make_api_response(
        {
            "report_id": report.id,
            "check_in_id": report.check_in_id,
            "status": report.status,
            "created_at": report.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        request_id,
    )
