from pathlib import Path
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "heat-environment-platform-backend"
    API_V1_PREFIX: str = "/api/v1"
    
    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@127.0.0.1:5432/gis_thermal_shanghai"
    DB_SCHEMA: str = "platform"
    
    # Security & Session
    SECRET_KEY: str = "heat-env-secret-key-2026-secure-token"
    SESSION_COOKIE_NAME: str = "heat_platform_session"
    SESSION_EXPIRE_HOURS: int = 12
    VIEW_EXPIRE_HOURS: int = 24
    IDEMPOTENCY_EXPIRE_HOURS: int = 24
    
    # Shanghai scene boundary & center
    SHANGHAI_CENTER_LAT: float = 31.2304
    SHANGHAI_CENTER_LON: float = 121.4737
    # Approximate bounding box [min_lon, min_lat, max_lon, max_lat]
    SHANGHAI_BBOX: list[float] = [120.85, 30.65, 122.25, 31.88]
    
    # Weather provider settings (Open-Meteo unauthenticated)
    OPEN_METEO_URL: str = "https://api.open-meteo.com/v1/forecast"
    WEATHER_REQUEST_TIMEOUT_SECONDS: int = 15
    WEATHER_PROVIDER: Literal['open_meteo_ecmwf', 'open_meteo_gfs', 'qweather'] = 'open_meteo_ecmwf'
    QWEATHER_API_HOST: str = ''
    QWEATHER_DEVELOPER_ID: str = ''
    QWEATHER_PROJECT_ID: str = ''
    QWEATHER_KEY_ID: str = ''
    QWEATHER_PRIVATE_KEY_PATH: str = 'secrets/qweather-private.pem'
    QWEATHER_JWT_TTL_SECONDS: int = Field(default=900, ge=120, le=86400)
    QWEATHER_FORECAST_HOURS: int = Field(default=48, ge=1, le=240)
    SPATIAL_MAX_POINTS: int = Field(default=25, ge=4, le=200)
    SPATIAL_CACHE_SECONDS: int = Field(default=3600, ge=60)
    
    # Tianditu online basemap key
    TIANDITU_KEY: str = ""
    
    # Storage & Exports
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    EXPORT_STORAGE_DIR: Path = BASE_DIR / "storage" / "exports"
    SPATIAL_STORAGE_DIR: Path = BASE_DIR.parent.parent / 'data' / 'derived' / 'qweather_spatial'

    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parent.parent / '.env', env_file_encoding='utf-8-sig', extra="allow")


settings = Settings()
