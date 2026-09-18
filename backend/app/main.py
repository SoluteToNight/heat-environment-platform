"""FastAPI application main entry point."""
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.db.init_db import init_platform_db
from app.db.session import SessionLocal
from app.routers.api_v1 import api_v1_router
from app.schemas.common import make_error_response
from app.services.weather_service import sync_weather_release


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure schema, tables, and initial seed
    print("[Startup] Initializing platform database schema...")
    init_platform_db()

    db = SessionLocal()
    try:
        print(f"[Startup] Checking weather provider: {settings.WEATHER_PROVIDER}")
        sync_weather_release(db)
    except Exception as e:
        db.rollback()
        print(f"[Startup Warning] Weather initial sync failed: {e}")
    finally:
        db.close()

    yield
    print("[Shutdown] heat-environment-platform backend shutting down.")


app = FastAPI(
    title="Heat Environment Platform API",
    description="上海市城市热暴露与体感打卡时空分析平台后端服务接口",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    req_id = request.headers.get("X-Request-Id") or f"req_{uuid.uuid4().hex[:10]}"
    request.state.request_id = req_id
    response: Response = await call_next(request)
    response.headers["X-Request-Id"] = req_id
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    req_id = getattr(request.state, "request_id", "req_err")
    code_str = f"HTTP_{exc.status_code}"
    return JSONResponse(
        status_code=exc.status_code,
        content=make_error_response(code_str, str(exc.detail), request_id=req_id),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    req_id = getattr(request.state, "request_id", "req_val_err")
    details = []
    for err in exc.errors():
        field = " -> ".join([str(x) for x in err.get("loc", [])])
        details.append({"field": field, "issue": err.get("msg", "Validation error")})

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=make_error_response("VALIDATION_ERROR", "Request validation failed", details=details, request_id=req_id),
    )


# Mount master API v1 router
app.include_router(api_v1_router, prefix=settings.API_V1_PREFIX)


@app.get("/health", tags=["System"])
def health_check(request: Request):
    req_id = getattr(request.state, "request_id", "req_health")
    return {"status": "ok", "service": settings.PROJECT_NAME, "request_id": req_id}
