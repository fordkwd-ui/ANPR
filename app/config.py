"""Application settings and configuration."""
import os
from functools import lru_cache
from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PROJECT_NAME: str = "Vehicle Gate Monitoring Cloud"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./anpr_test.db"

    # JWT Authentication
    JWT_SECRET: str = "super-secret-key-forest-gate-change-in-prod-2026"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Storage: "s3" or "local"
    STORAGE_DRIVER: str = "local"
    STORAGE_LOCAL_DIR: str = "./media_storage"
    S3_ENDPOINT_URL: Optional[str] = "http://localhost:9000"
    S3_ACCESS_KEY: Optional[str] = "minioadmin"
    S3_SECRET_KEY: Optional[str] = "minioadmin"
    S3_BUCKET_NAME: str = "anpr-media"
    S3_REGION: str = "us-east-1"
    PRESIGNED_URL_EXPIRE_SECONDS: int = 600

    # Gate Box Clip Tunnel URL (optional)
    CLIP_BASE_URL: Optional[str] = None

    # Review Thresholds
    CONF_THRESHOLD_LOAD: float = 0.60
    CONF_THRESHOLD_PLATE: float = 0.85

    # Security Lockout
    MAX_FAILED_LOGINS: int = 5
    LOCKOUT_MINUTES: int = 15

    # Retention
    MEDIA_RETENTION_DAYS: int = 90

    # Timezone & CORS
    DEFAULT_TIMEZONE: str = "Asia/Kolkata"
    CORS_ORIGINS: List[str] = Field(default_factory=lambda: ["*"])


@lru_cache()
def get_settings() -> Settings:
    return Settings()
