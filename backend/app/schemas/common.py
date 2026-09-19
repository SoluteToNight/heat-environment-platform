"""Common schema contracts and response wrappers."""
import datetime
from typing import Any, Generic, Optional, TypeVar
from pydantic import BaseModel, Field


def utc_now_str() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_utc_z(value: datetime.datetime) -> str:
    """timestamptz 字段 → UTC Z 文本。

    必须先 astimezone(UTC) 再落 Z 后缀：psycopg2 按会话时区返回 aware datetime，
    直接 strftime 加 Z 会把时刻错标 8 小时（评审报告 C2 同类问题）。
    """
    return value.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
