"""Schemas for data export requests and status."""
from typing import Optional
from pydantic import BaseModel, Field


class CreateExportRequest(BaseModel):
    export_type: str = Field(..., description="'environment_table', 'my_check_ins', 'public_check_ins'")
    file_format: str = Field(default="csv", description="'csv' or 'geojson'")
    scene_id: str = "scene_shanghai"
    view_id: Optional[str] = Field(None, description="Required for environment_table")
    bbox: Optional[list[float]] = Field(None, description="Optional bounding box [min_lon, min_lat, max_lon, max_lat]")
    start_time: Optional[str] = None
    end_time: Optional[str] = None


class ExportStatusResponse(BaseModel):
    export_id: str
    task_id: str
    export_type: str
    file_format: str
    status: str  # processing, ready, failed, expired
    file_size_bytes: int = 0
    download_url: Optional[str] = None
    sha256_hash: Optional[str] = None
    expires_at: Optional[str] = None
