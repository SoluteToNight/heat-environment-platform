"""Master API v1 router consolidating all submodules."""
from fastapi import APIRouter

from app.routers.auth import router as auth_router
from app.routers.check_ins import router as check_ins_router
from app.routers.environment import router as env_router
from app.routers.exports import router as exports_router
from app.routers.scenes import router as scenes_router
from app.routers.tasks import router as tasks_router
from app.routers.spatial import router as spatial_router
from app.routers.forecast import router as forecast_router

api_v1_router = APIRouter()

api_v1_router.include_router(auth_router)
api_v1_router.include_router(scenes_router)
api_v1_router.include_router(env_router)
api_v1_router.include_router(check_ins_router)
api_v1_router.include_router(tasks_router)
api_v1_router.include_router(exports_router)
api_v1_router.include_router(spatial_router)
api_v1_router.include_router(forecast_router)
