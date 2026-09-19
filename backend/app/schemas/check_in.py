"""Schemas for UGC check-ins, aggregates, updates, and moderation reports."""
import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


class GeoPoint(BaseModel):
    type: str = "Point"
    coordinates: list[float] = Field(..., description="[longitude, latitude] in EPSG:4326")


class CheckInCreateRequest(BaseModel):
    scene_id: str = Field(default="scene_shanghai", description="Scene ID")
    location: GeoPoint
    location_source: str = Field(default="manual_map")
    horizontal_accuracy_m: Optional[float] = None
    experienced_at: datetime.datetime
    time_source: str = Field(default="user_selected")
    time_uncertainty_minutes: Optional[int] = None
    thermal_sensation: str = Field(..., description="'cold', 'cool', 'neutral', 'warm', 'hot'")
    thermal_comfort: Optional[str] = Field(None, description="'comfortable', 'ordinary', 'uncomfortable'")
    setting: str = Field(default="outdoor", description="'indoor', 'outdoor', 'mixed', 'unknown'")
    activity: Optional[str] = None
    sun_exposure: Optional[str] = None
    note: Optional[str] = Field(None, max_length=1000)
    visibility: str = Field(default="public", description="'public' or 'private'")
    public_location_precision: str = Field(default="grid_200m", description="'exact' or 'grid_200m'")


class CheckInUpdateRequest(BaseModel):
    location: Optional[GeoPoint] = None
    location_source: Optional[str] = None
    horizontal_accuracy_m: Optional[float] = None
    experienced_at: Optional[datetime.datetime] = None
    time_source: Optional[str] = None
    time_uncertainty_minutes: Optional[int] = None
    thermal_sensation: Optional[str] = None
    thermal_comfort: Optional[str] = None
    setting: Optional[str] = None
    activity: Optional[str] = None
    sun_exposure: Optional[str] = None
    note: Optional[str] = Field(None, max_length=1000)
    visibility: Optional[str] = None
    public_location_precision: Optional[str] = None


class CheckInPublicItem(BaseModel):
    id: str
    scene_id: str
    location: GeoPoint
    public_location_precision: str
    experienced_at: str
    thermal_sensation: str
    thermal_comfort: Optional[str] = None
    setting: str
    activity: Optional[str] = None
    sun_exposure: Optional[str] = None
    note: Optional[str] = None
    created_at: str


class MatchedEnvironment(BaseModel):
    temperature_2m: Optional[float] = None
    relative_humidity_2m: Optional[float] = None
    wind_speed_10m: Optional[float] = None
    shortwave_radiation: Optional[float] = None
    release_id: Optional[str] = None


class CheckInOwnerItem(BaseModel):
    id: str
    scene_id: str
    owner_id: str
    exact_location: GeoPoint
    public_location: GeoPoint
    public_location_precision: str
    location_source: str
    horizontal_accuracy_m: Optional[float] = None
    experienced_at: str
    time_source: str
    time_uncertainty_minutes: Optional[int] = None
    thermal_sensation: str
    thermal_comfort: Optional[str] = None
    setting: str
    activity: Optional[str] = None
    sun_exposure: Optional[str] = None
    note: Optional[str] = None
    visibility: str
    publication_status: str
    revision: int
    match_status: str
    matched_environment: Optional[MatchedEnvironment] = None
    created_at: str
    updated_at: str


class CheckInAggregateItem(BaseModel):
    grid_id: str
    center_lon: float
    center_lat: float
    total_count: int
    sensation_counts: dict[str, int]


class ReportCreateRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500, description="Report rationale")
