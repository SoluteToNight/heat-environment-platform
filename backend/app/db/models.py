"""SQLAlchemy ORM models in platform schema."""
import datetime
import uuid
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry

from app.db.session import Base

SCHEMA_NAME = "platform"


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": SCHEMA_NAME}

    id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    display_name = Column(String(64), nullable=False)
    role = Column(String(32), default="user", nullable=False)  # 'user' or 'admin'
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")
    check_ins = relationship("UgcCheckIn", back_populates="owner")


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = {"schema": SCHEMA_NAME}

    id = Column(String(128), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(64), ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_revoked = Column(Boolean, default=False, nullable=False)

    user = relationship("User", back_populates="sessions")


class Scene(Base):
    __tablename__ = "scenes"
    __table_args__ = {"schema": SCHEMA_NAME}

    id = Column(String(64), primary_key=True)  # e.g. 'scene_shanghai'
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    center_lon = Column(Float, nullable=False)
    center_lat = Column(Float, nullable=False)
    bbox = Column(JSON, nullable=False)  # [min_lon, min_lat, max_lon, max_lat]
    status = Column(String(32), default="active", nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class EnvRelease(Base):
    __tablename__ = "env_releases"
    __table_args__ = {"schema": SCHEMA_NAME}

    id = Column(String(128), primary_key=True)  # e.g. 'rel_20260916_ecmwf_12'
    scene_id = Column(String(64), nullable=False, default="scene_shanghai", index=True)
    product_id = Column(String(64), nullable=False, index=True)  # 'open_meteo_ecmwf' or 'open_meteo_gfs'
    model_source = Column(String(256), nullable=False)
    time_start = Column(DateTime(timezone=True), nullable=False)
    time_end = Column(DateTime(timezone=True), nullable=False)
    computed_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    freshness = Column(String(32), default="fresh", nullable=False)  # fresh, stale, unknown
    availability = Column(String(32), default="available", nullable=False)
    raw_meta = Column(JSON, nullable=True)

    records = relationship("WeatherRecord", back_populates="release", cascade="all, delete-orphan")


class WeatherRecord(Base):
    __tablename__ = "weather_records"
    __table_args__ = (
        Index("idx_weather_rel_time", "release_id", "target_time"),
        {"schema": SCHEMA_NAME},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    release_id = Column(String(128), ForeignKey(f"{SCHEMA_NAME}.env_releases.id", ondelete="CASCADE"), nullable=False)
    target_time = Column(DateTime(timezone=True), nullable=False, index=True)
    lon = Column(Float, nullable=False)
    lat = Column(Float, nullable=False)
    temperature_2m = Column(Float, nullable=True)  # °C
    relative_humidity_2m = Column(Float, nullable=True)  # %
    wind_speed_10m = Column(Float, nullable=True)  # m/s
    wind_direction_10m = Column(Float, nullable=True)  # deg
    shortwave_radiation = Column(Float, nullable=True)  # W/m² (GHI)
    direct_radiation = Column(Float, nullable=True)  # W/m²
    diffuse_radiation = Column(Float, nullable=True)  # W/m²
    direct_normal_irradiance = Column(Float, nullable=True)  # W/m² (DNI)

    release = relationship("EnvRelease", back_populates="records")


class EnvView(Base):
    __tablename__ = "env_views"
    __table_args__ = {"schema": SCHEMA_NAME}

    id = Column(String(128), primary_key=True, default=lambda: f"view_{uuid.uuid4().hex}")
    scene_id = Column(String(64), nullable=False, default="scene_shanghai")
    requested_time = Column(DateTime(timezone=True), nullable=False)
    resolved_time = Column(DateTime(timezone=True), nullable=False)
    time_selection_kind = Column(String(32), nullable=False)  # 'now' or 'at'
    release_selection_mode = Column(String(32), nullable=False)  # 'latest' or 'pinned'
    variables = Column(JSON, nullable=False)
    pinned_releases = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)


class UgcCheckIn(Base):
    __tablename__ = "ugc_check_ins"
    __table_args__ = (
        Index("idx_checkin_owner_created", "owner_id", "created_at"),
        Index("idx_checkin_time_vis", "experienced_at", "visibility", "publication_status"),
        Index("idx_checkin_idemp", "owner_id", "idempotency_key", unique=False),
        {"schema": SCHEMA_NAME},
    )

    id = Column(String(64), primary_key=True, default=lambda: f"chk_{uuid.uuid4().hex[:12]}")
    scene_id = Column(String(64), nullable=False, default="scene_shanghai")
    owner_id = Column(String(64), ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="CASCADE"), nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    request_hash = Column(String(64), nullable=False)

    # Exact location (kept private/restricted)
    exact_lon = Column(Float, nullable=False)
    exact_lat = Column(Float, nullable=False)
    geom_exact = Column(Geometry("POINT", srid=4326), nullable=True)

    # Coarsened location for public view
    coarse_lon = Column(Float, nullable=False)
    coarse_lat = Column(Float, nullable=False)
    geom_coarse = Column(Geometry("POINT", srid=4326), nullable=True)

    public_location_precision = Column(String(32), default="grid_200m", nullable=False)  # 'exact' or 'grid_200m'
    location_source = Column(String(64), default="manual_map", nullable=False)
    horizontal_accuracy_m = Column(Float, nullable=True)

    experienced_at = Column(DateTime(timezone=True), nullable=False)
    time_source = Column(String(64), default="user_selected", nullable=False)
    time_uncertainty_minutes = Column(Integer, nullable=True)

    thermal_sensation = Column(String(32), nullable=False)  # cold, cool, neutral, warm, hot
    thermal_comfort = Column(String(32), nullable=True)  # comfortable, ordinary, uncomfortable
    setting = Column(String(32), default="outdoor", nullable=False)  # indoor, outdoor, mixed, unknown
    activity = Column(String(64), nullable=True)
    sun_exposure = Column(String(64), nullable=True)
    note = Column(String(1000), nullable=True)

    visibility = Column(String(32), default="public", nullable=False)  # private, public
    publication_status = Column(String(32), default="published", nullable=False)  # pending, published, rejected, hidden
    revision = Column(Integer, default=1, nullable=False)

    match_status = Column(String(32), default="pending", nullable=False)  # pending, matched, unmatched, failed
    matched_temperature = Column(Float, nullable=True)
    matched_humidity = Column(Float, nullable=True)
    matched_wind_speed = Column(Float, nullable=True)
    matched_radiation = Column(Float, nullable=True)
    matched_release_id = Column(String(128), nullable=True)

    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)

    owner = relationship("User", back_populates="check_ins")


class UgcReport(Base):
    __tablename__ = "ugc_reports"
    __table_args__ = {"schema": SCHEMA_NAME}

    id = Column(String(64), primary_key=True, default=lambda: f"rep_{uuid.uuid4().hex[:12]}")
    check_in_id = Column(String(64), ForeignKey(f"{SCHEMA_NAME}.ugc_check_ins.id", ondelete="CASCADE"), nullable=False)
    reporter_id = Column(String(64), ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="CASCADE"), nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    reason = Column(Text, nullable=False)
    status = Column(String(32), default="pending", nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class SystemTask(Base):
    __tablename__ = "system_tasks"
    __table_args__ = {"schema": SCHEMA_NAME}

    id = Column(String(64), primary_key=True, default=lambda: f"task_{uuid.uuid4().hex[:12]}")
    task_type = Column(String(64), nullable=False)  # 'weather_sync', 'env_match', 'export'
    owner_id = Column(String(64), nullable=True)
    status = Column(String(32), default="queued", nullable=False)  # queued, running, success, failed, cancelled
    progress_pct = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    result_meta = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class ExportRecord(Base):
    __tablename__ = "export_records"
    __table_args__ = {"schema": SCHEMA_NAME}

    id = Column(String(64), primary_key=True, default=lambda: f"exp_{uuid.uuid4().hex[:12]}")
    task_id = Column(String(64), ForeignKey(f"{SCHEMA_NAME}.system_tasks.id", ondelete="CASCADE"), nullable=False)
    owner_id = Column(String(64), ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="CASCADE"), nullable=False)
    export_type = Column(String(64), nullable=False)  # environment_table, my_check_ins, public_check_ins
    file_format = Column(String(32), default="csv", nullable=False)
    file_path = Column(String(512), nullable=False)
    file_size_bytes = Column(Integer, default=0, nullable=False)
    sha256_hash = Column(String(64), nullable=True)
    status = Column(String(32), default="processing", nullable=False)  # processing, ready, failed, expired
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
