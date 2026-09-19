"""FastAPI Router for 24-Hour UTCI & Subjective Thermal Perception Inversion."""

import logging
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.schemas.common import make_api_response
from app.services.heat_perception_service import heat_perception_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["heat-perception-inversion"])

MAPS_DIR = Path(__file__).resolve().parents[3] / "frontend" / "public" / "maps"
ROOT_DIR = Path(__file__).resolve().parents[3]

class CustomInversionBody(BaseModel):
    air_temperature_c: float = Field(..., ge=-10.0, le=55.0, description="空气温度 (°C)")
    relative_humidity_pct: float = Field(..., ge=10.0, le=100.0, description="相对湿度 (%)")
    wind_speed_10m_ms: float = Field(..., ge=0.0, le=30.0, description="10米风速 (m/s)")
    net_solar_radiation_wm2: float = Field(0.0, ge=0.0, le=1200.0, description="净太阳辐射 (W/m²)")
    green_fraction: float = Field(0.10, ge=0.0, le=1.0, description="绿地覆盖率 (0-1)")
    water_fraction: float = Field(0.05, ge=0.0, le=1.0, description="水体覆盖率 (0-1)")
    building_fraction: float = Field(0.15, ge=0.0, le=1.0, description="建筑覆盖率 (0-1)")

@router.get("/forecast/24h/summary")
def get_24h_forecast_summary(request: Request):
    """获取未来24小时全市宏观逐小时UTCI、主观偏热感知概率P(hot)与综合风险等级"""
    req_id = getattr(request.state, "request_id", "req_fc24h_summary")
    try:
        data = heat_perception_service.get_24h_summary()
        return make_api_response(data, req_id)
    except Exception as exc:
        logger.error("24h summary error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"反演时序生成失败: {exc}")

@router.get("/forecast/24h/grid")
def get_24h_spatial_grid(
    request: Request,
    lead_hour: int = Query(5, ge=1, le=24, description="预报提前时效 (1-24小时)")
):
    """获取指定提前时效下上海全市 497 网格微环境修正空间反演 GeoJSON"""
    req_id = getattr(request.state, "request_id", "req_fc24h_grid")
    try:
        geojson_data = heat_perception_service.get_24h_grid(lead_hour=lead_hour)
        return make_api_response(geojson_data, req_id)
    except Exception as exc:
        logger.error("24h grid error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"网格反演失败: {exc}")

@router.get("/forecast/24h/multitemporal")
def get_24h_multitemporal_grids(request: Request):
    """获取清晨、午后峰值、傍晚、夜间四时相全景时空演化 GeoJSON"""
    req_id = getattr(request.state, "request_id", "req_fc24h_multi")
    try:
        geojson_data = heat_perception_service.get_24h_multitemporal_grids()
        return make_api_response(geojson_data, req_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@router.get("/forecast/24h/extreme_regions")
def get_24h_extreme_regions(
    request: Request,
    lead_hour: int = Query(5, ge=1, le=24, description="预报提前时效 (默认正午极值小时)")
):
    """获取未来24小时主观热感知极值区域 (Top 10 极值网格与各行政区风险排行)"""
    req_id = getattr(request.state, "request_id", "req_fc24h_extreme")
    try:
        data = heat_perception_service.get_extreme_regions(lead_hour=lead_hour)
        return make_api_response(data, req_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@router.get("/forecast/24h/decision")
def get_24h_decision_support(request: Request):
    """获取未来24小时分级应急响应指令、行业行动策略与防暑驿站布局"""
    req_id = getattr(request.state, "request_id", "req_fc24h_decision")
    try:
        data = heat_perception_service.get_decision_support()
        return make_api_response(data, req_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@router.get("/models/evaluation")
def get_models_evaluation(request: Request):
    """获取多历年 M0 与 M1 回归模型性能指标 (AUC=0.9306, 准确率=90.0%) 及优势比"""
    req_id = getattr(request.state, "request_id", "req_models_eval")
    try:
        data = heat_perception_service.get_model_evaluation()
        return make_api_response(data, req_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@router.post("/forecast/custom_inversion")
def run_custom_inversion(body: CustomInversionBody, request: Request):
    """支持前端自定义传入任意气象参数与下垫面参数的前向实时反演"""
    req_id = getattr(request.state, "request_id", "req_custom_inversion")
    try:
        data = heat_perception_service.custom_inversion(
            ta=body.air_temperature_c,
            rh=body.relative_humidity_pct,
            v=body.wind_speed_10m_ms,
            rad=body.net_solar_radiation_wm2,
            green=body.green_fraction,
            water=body.water_fraction,
            bldg=body.building_fraction
        )
        return make_api_response(data, req_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@router.get("/forecast/24h/maps/{map_name}")
def get_map_figure(map_name: str):
    """获取 13 幅高清学术级 GIS 专题图静态图片"""
    # 优先从公共 maps 目录或项目根目录查找
    candidates = [
        MAPS_DIR / map_name,
        ROOT_DIR / map_name,
        ROOT_DIR.parent / "backend" / "artifacts" / "figures" / map_name
    ]
    for c in candidates:
        if c.exists():
            return FileResponse(c, media_type="image/png")
    raise HTTPException(status_code=404, detail=f"未找到地图文件: {map_name}")
