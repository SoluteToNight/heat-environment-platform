"""Common schema contracts and response wrappers."""
import datetime
from typing import Any, Generic, Optional, TypeVar
from pydantic import BaseModel, Field


def utc_now_str() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


T = TypeVar("T")


class ResponseMeta(BaseModel):
    request_id: str = Field(..., description="Unique request identifier")
    server_time: str = Field(default_factory=utc_now_str, description="Server timestamp in UTC Z format")


class APIResponse(BaseModel, Generic[T]):
    data: T
    meta: ResponseMeta


class ErrorDetail(BaseModel):
    field: Optional[str] = None
    issue: str


class ErrorInfo(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: ErrorInfo
    meta: ResponseMeta


def make_api_response(data: Any, request_id: str) -> dict:
    return {
        "data": data,
        "meta": {
            "request_id": request_id,
            "server_time": utc_now_str(),
        },
    }


def make_error_response(code: str, message: str, details: list = None, request_id: str = "req_err") -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or [],
        },
        "meta": {
            "request_id": request_id,
            "server_time": utc_now_str(),
        },
    }
