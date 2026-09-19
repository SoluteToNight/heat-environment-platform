"""Authentication and session management router."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.schemas.auth import LoginRequest, SessionResponse, SessionUser
from app.schemas.common import format_utc_z, make_api_response
from app.services.auth_service import (
    authenticate_user,
    create_user_session,
    extract_session_id,
    get_current_user,
    get_optional_current_user,
    get_session_by_id,
    revoke_user_session,
)

router = APIRouter(prefix="/auth", tags=["A04 身份与访问控制"])


@router.post("/login")
def login(
    req: LoginRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_login")
    user = authenticate_user(db, req.username, req.password)
    if not user:
        # Generic message without leaking account existence
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    session = create_user_session(db, user.id)

    # Set HttpOnly session cookie
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=session.id,
        httponly=True,
        samesite="lax",
        secure=False,  # Set True in production with HTTPS
        max_age=settings.SESSION_EXPIRE_HOURS * 3600,
    )

    data = SessionResponse(
        is_authenticated=True,
        session_id=session.id,
        expires_at=format_utc_z(session.expires_at),
        user=SessionUser(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=user.role,
        ),
    )
    return make_api_response(data.model_dump(), request_id)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    session_id: Optional[str] = Depends(extract_session_id),
    db: Session = Depends(get_db),
):
    if session_id:
        revoke_user_session(db, session_id)
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/session")
def get_session_info(
    request: Request,
    current_user=Depends(get_optional_current_user),
    session_id: Optional[str] = Depends(extract_session_id),
    db: Session = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_session")
    if not current_user or not session_id:
        data = SessionResponse(is_authenticated=False)
        return make_api_response(data.model_dump(), request_id)

    session = get_session_by_id(db, session_id)
    expires_str = format_utc_z(session.expires_at) if session else None

    data = SessionResponse(
        is_authenticated=True,
        session_id=session_id,
        expires_at=expires_str,
        user=SessionUser(
            id=current_user.id,
            username=current_user.username,
            display_name=current_user.display_name,
            role=current_user.role,
        ),
    )
    return make_api_response(data.model_dump(), request_id)
