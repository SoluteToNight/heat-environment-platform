"""Schemas for identity and authentication."""
from typing import Optional
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., description="Username")
    password: str = Field(..., description="Password")


class SessionUser(BaseModel):
    id: str
    username: str
    display_name: str
    role: str


class SessionResponse(BaseModel):
    is_authenticated: bool
    user: Optional[SessionUser] = None
    session_id: Optional[str] = None
    expires_at: Optional[str] = None
