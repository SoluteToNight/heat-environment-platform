"""Schemas for environment exploration, catalog, releases, views, and readings."""
from typing import Any, Optional
from pydantic import BaseModel, Field


class CatalogVariable(BaseModel):
    code: str
    name: str
    unit: str
    description: str
    availability: str = "available"  # available, missing, unsupported


class ProductCatalog(BaseModel):
    product_id: str
    name: str
    model_source: str
    description: str
    variables: list[CatalogVariable]


class ReleaseItem(BaseModel):
    release_id: str
    product_id: str
    model_source: str
    time_start: str
    time_end: str
    freshness: str  # fresh, stale, unknown
    availability: str  # available, missing, unsupported


class TimeSelection(BaseModel):
    kind: str = Field(..., description="'now' or 'at'")
    time: Optional[str] = Field(None, description="RFC 3339 timestamp if kind is 'at'")


class ReleaseSelection(BaseModel):
    mode: str = Field(default="latest", description="'latest' or 'pinned'")
    release_ids: Optional[list[str]] = Field(None, description="Explicit release IDs if pinned")


class CreateViewRequest(BaseModel):
    scene_id: str = "scene_shanghai"
    variables: list[str] = Field(..., description="List of variable codes")
    time_selection: TimeSelection
    release_selection: ReleaseSelection = Field(default_factory=ReleaseSelection)


class ViewVariableDetail(BaseModel):
    product_id: str
    variable: str
    release_id: str
    unit: str
    availability: str
    freshness: str
    reason_code: Optional[str] = None
    provenance: Optional[dict[str, Any]] = None


class ViewResponse(BaseModel):
    view_id: str
    scene_id: str
    requested_time: str
    resolved_time: str
    variables: list[ViewVariableDetail]
    expires_at: str


class PointReading(BaseModel):
    variable: str
    value: Optional[float] = None
    unit: str
    value_status: str  # valid, no_data, outside_coverage, incompatible
    reason_code: Optional[str] = None


class PointResponse(BaseModel):
    view_id: str
    lon: float
    lat: float
    target_time: str
    readings: list[PointReading]
    elevation_m: Optional[float] = None
    slope_deg: Optional[float] = None


class SeriesTimeStep(BaseModel):
    time: str
    values: dict[str, Optional[float]]
    status: dict[str, str]


class SeriesResponse(BaseModel):
    view_id: str
    lon: float
    lat: float
    steps: list[SeriesTimeStep]
