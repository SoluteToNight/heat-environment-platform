"""Authentication and user session services."""
import datetime
import uuid
import bcrypt
from typing import Optional
from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.db.models import User, UserSession, utc_now


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def hash_password(plain_password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain_password.encode("utf-8"), salt).decode("utf-8")


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    user = db.query(User).filter(User.username == username, User.is_active.is_(True)).first()
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def create_user_session(db: Session, user_id: str) -> UserSession:
    now = utc_now()
    expires_at = now + datetime.timedelta(hours=settings.SESSION_EXPIRE_HOURS)
    session_id = f"sess_{uuid.uuid4().hex}"
    session = UserSession(
        id=session_id,
        user_id=user_id,
        created_at=now,
        expires_at=expires_at,
        is_revoked=False,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def revoke_user_session(db: Session, session_id: str) -> bool:
    session = db.query(UserSession).filter(UserSession.id == session_id).first()
    if session:
        session.is_revoked = True
        db.commit()
        return True
    return False


def get_session_by_id(db: Session, session_id: str) -> Optional[UserSession]:
    now = utc_now()
    session = (
        db.query(UserSession)
        .filter(
            UserSession.id == session_id,
            UserSession.is_revoked.is_(False),
            UserSession.expires_at > now,
        )
        .first()
    )
    return session


def extract_session_id(
    cookie_session: Optional[str] = Cookie(None, alias=settings.SESSION_COOKIE_NAME),
    authorization: Optional[str] = Header(None),
) -> Optional[str]:
    """Extract session token from HttpOnly Cookie or Bearer header."""
    if cookie_session:
        return cookie_session
    if authorization and authorization.startswith("Bearer "):
        return authorization.split("Bearer ", 1)[1].strip()
    return None


def get_current_user(
    session_id: Optional[str] = Depends(extract_session_id),
    db: Session = Depends(get_db),
) -> User:
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    user_session = get_session_by_id(db, session_id)
    if not user_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalid or expired",
        )
    user = db.query(User).filter(User.id == user_session.user_id, User.is_active.is_(True)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user


def get_optional_current_user(
    session_id: Optional[str] = Depends(extract_session_id),
    db: Session = Depends(get_db),
) -> Optional[User]:
    if not session_id:
        return None
    user_session = get_session_by_id(db, session_id)
    if not user_session:
        return None
    return db.query(User).filter(User.id == user_session.user_id, User.is_active.is_(True)).first()


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operation requires administrative privileges",
        )
    return current_user
