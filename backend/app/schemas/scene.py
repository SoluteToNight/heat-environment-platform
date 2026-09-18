"""Schemas for scenes, layers, places, and spatial features."""
from typing import Any, Optional
from pydantic import BaseModel, Field


class SceneListItem(BaseModel):
    id: str
    name: str
    status: str
    center: list[float]
    bbox: list[float]


class SceneDetail(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    center: list[float]
    bbox: list[float]
    status: str
    timezone: str = "Asia/Shanghai"
    tianditu_key: Optional[str] = None
    default_layers: list[str] = Field(default_factory=lambda: ["layer_admin", "layer_buildings", "layer_roads", "layer_green", "layer_water"])


class LayerInfo(BaseModel):
    layer_id: str
    name: str
    type: str  # vector, raster, 3dtiles, geojson
    attribution: str
    description: Optional[str] = None
    is_visible_default: bool = True
    capabilities: dict[str, bool] = Field(default_factory=lambda: {"pick": True, "filter": True})


class PlaceItem(BaseModel):
    id: str
    title: str
    poi_type: Optional[str] = None
    lon: float
    lat: float


class FeatureItem(BaseModel):
    id: str
    layer_id: str
    properties: dict[str, Any]
    geometry: dict[str, Any]
