#!/usr/bin/env python3
"""
ReceiptAI Configuration Settings
================================

Production-ready configuration using Pydantic for validation.
Supports Railway deployment with environment-specific settings.

Usage:
    from config.settings import settings
    print(settings.DATABASE_URL)
"""

import os
from typing import Optional, List
from functools import lru_cache

try:
    from pydantic_settings import BaseSettings
    from pydantic import Field, validator
except ImportError:
    # Fallback for older pydantic
    from pydantic import BaseSettings, Field, validator


class Settings(BaseSettings):
    """
    Application settings with environment variable support.

    All settings can be overridden via environment variables.
    Railway automatically injects many of these.
    """

    # ==========================================================================
    # ENVIRONMENT
    # ==========================================================================
    RAILWAY_ENVIRONMENT: str = Field(default="development", description="Railway environment name")
    RAILWAY_ENVIRONMENT_NAME: str = Field(default="development")
    DEBUG: bool = Field(default=False, description="Enable debug mode")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")

    @property
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.RAILWAY_ENVIRONMENT == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development."""
        return self.RAILWAY_ENVIRONMENT == "development"

    # ==========================================================================
    # DATABASE
    # ==========================================================================
    MYSQL_URL: str = Field(default="", description="MySQL connection URL")
    DATABASE_URL: Optional[str] = Field(default=None, description="Alternative database URL")

    # Connection pool settings (optimized for Railway)
    DB_POOL_SIZE: int = Field(default=20, description="Connection pool size")
    DB_MAX_OVERFLOW: int = Field(default=30, description="Max overflow connections")
    DB_POOL_TIMEOUT: int = Field(default=60, description="Pool timeout in seconds")
    DB_POOL_RECYCLE: int = Field(default=300, description="Connection recycle time (Railway optimized)")

    # Read-only mode for development accessing production DB
    DB_READ_ONLY: bool = Field(default=False, description="Database read-only mode")

    @property
    def database_url(self) -> str:
        """Get the effective database URL."""
        return self.DATABASE_URL or self.MYSQL_URL

    @validator('DB_READ_ONLY', pre=True)
    def parse_bool(cls, v):
        if isinstance(v, str):
            return v.lower() in ('true', '1', 'yes')
        return bool(v)

    # ==========================================================================
    # CLOUDFLARE R2 STORAGE
    # ==========================================================================
    R2_ACCOUNT_ID: str = Field(default="", description="Cloudflare account ID")
    R2_ACCESS_KEY_ID: str = Field(default="", description="R2 access key")
    R2_SECRET_ACCESS_KEY: str = Field(default="", description="R2 secret key")
    R2_BUCKET_NAME: str = Field(default="bkreceipts", description="R2 bucket name")
    R2_ENDPOINT: str = Field(default="", description="R2 endpoint URL")
    R2_PUBLIC_URL: str = Field(default="", description="R2 public URL for serving files")
    R2_TOKEN: str = Field(default="", description="R2 API token")

    # Backup bucket (separate from main storage)
    R2_BACKUP_BUCKET: str = Field(default="bkreceipts-backups", description="R2 backup bucket")

    # ==========================================================================
    # AI/ML SERVICES
    # ==========================================================================
    OPENAI_API_KEY: str = Field(default="", description="OpenAI API key")
    GEMINI_API_KEY: str = Field(default="", description="Google Gemini API key")
    GEMINI_API_KEY_2: str = Field(default="", description="Backup Gemini key")
    GEMINI_API_KEY_3: str = Field(default="", description="Backup Gemini key 2")
    ANTHROPIC_API_KEY: str = Field(default="", description="Anthropic Claude API key")

    # AI feature flags
    AI_MODEL: str = Field(default="gpt-4o-mini", description="Default AI model")
    AI_CONFIDENCE_THRESHOLD: float = Field(default=0.85, description="AI confidence threshold")
    ENABLE_AI_BUSINESS_INFERENCE: bool = Field(default=True)
    ENABLE_SMART_NOTES: bool = Field(default=True)
    ENABLE_TIP_DETECTION: bool = Field(default=True)

    # OCR settings
    OCR_ENGINE: str = Field(default="paddleocr", description="OCR engine")
    OCR_LANG: str = Field(default="en", description="OCR language")

    # ==========================================================================
    # GOOGLE APIs
    # ==========================================================================
    GOOGLE_OAUTH_CREDENTIALS: str = Field(default="", description="Google OAuth credentials JSON")

    # Gmail tokens for each account
    GMAIL_TOKEN_KAPLAN_BRIAN_GMAIL_COM: str = Field(default="")
    GMAIL_TOKEN_BRIAN_BUSINESS_COM: str = Field(default="")
    GMAIL_TOKEN_BRIAN_SECONDARY_COM: str = Field(default="")
    GMAIL_TOKEN_BRIAN_KAPLAN_COM: str = Field(default="")

    # Calendar tokens
    CALENDAR_TOKEN: str = Field(default="")
    CALENDAR_TOKENS: str = Field(default="")

    # ==========================================================================
    # APPLICATION
    # ==========================================================================
    SECRET_KEY: str = Field(default="change-me-in-production", description="Flask secret key")
    PORT: int = Field(default=5050, description="Server port")
    HOST: str = Field(default="0.0.0.0", description="Server host")

    # Authentication
    AUTH_PASSWORD: str = Field(default="", description="Admin password")
    AUTH_PIN: str = Field(default="", description="PIN for quick access")
    ADMIN_API_KEY: str = Field(default="", description="Admin API key")

    # File paths
    LOG_DIR: str = Field(default="logs", description="Log directory")
    BACKUP_DIR: str = Field(default="backups", description="Backup directory")
    AUTO_BACKUP: bool = Field(default=True, description="Enable auto backups")

    # ==========================================================================
    # RAILWAY SPECIFIC
    # ==========================================================================
    RAILWAY_PROJECT_ID: str = Field(default="")
    RAILWAY_SERVICE_ID: str = Field(default="")
    RAILWAY_ENVIRONMENT_ID: str = Field(default="")
    RAILWAY_PUBLIC_DOMAIN: str = Field(default="")
    RAILWAY_PRIVATE_DOMAIN: str = Field(default="")
    RAILWAY_STATIC_URL: str = Field(default="")
    RAILWAY_SERVICE_WEB_URL: str = Field(default="")

    # ==========================================================================
    # MONITORING
    # ==========================================================================
    DATADOG_API_KEY: Optional[str] = Field(default=None, description="Datadog API key")
    SENTRY_DSN: Optional[str] = Field(default=None, description="Sentry DSN")

    # Alert thresholds
    ALERT_ERROR_RATE_THRESHOLD: int = Field(default=10, description="Errors per minute to trigger alert")
    ALERT_RESPONSE_TIME_THRESHOLD: int = Field(default=5000, description="Response time ms threshold")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# ==========================================================================
# ENVIRONMENT-SPECIFIC CONFIGS
# ==========================================================================

class DevelopmentSettings(Settings):
    """Development-specific settings."""
    DEBUG: bool = True
    LOG_LEVEL: str = "DEBUG"
    DB_READ_ONLY: bool = True  # Safety: dev uses prod DB read-only


class ProductionSettings(Settings):
    """Production-specific settings."""
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    DB_READ_ONLY: bool = False


class TestSettings(Settings):
    """Test environment settings."""
    DEBUG: bool = True
    LOG_LEVEL: str = "DEBUG"
    DB_READ_ONLY: bool = True
    MYSQL_URL: str = "mysql://root:testpassword@localhost:3306/receiptai_test"


# ==========================================================================
# SETTINGS FACTORY
# ==========================================================================

@lru_cache()
def get_settings() -> Settings:
    """
    Get settings based on environment.

    Uses caching to avoid re-reading environment variables.
    """
    env = os.environ.get("RAILWAY_ENVIRONMENT", "development")

    if env == "production":
        return ProductionSettings()
    elif env == "test":
        return TestSettings()
    else:
        return DevelopmentSettings()


# Global settings instance
settings = get_settings()


# ==========================================================================
# VALIDATION HELPERS
# ==========================================================================

def validate_settings():
    """
    Validate that all required settings are configured.

    Call this at application startup.
    """
    errors = []

    # Required for all environments
    if not settings.database_url:
        errors.append("MYSQL_URL or DATABASE_URL is required")

    if not settings.SECRET_KEY or settings.SECRET_KEY == "change-me-in-production":
        if settings.is_production:
            errors.append("SECRET_KEY must be set in production")

    # Required for production
    if settings.is_production:
        if not settings.R2_ACCESS_KEY_ID:
            errors.append("R2_ACCESS_KEY_ID is required in production")

        if not settings.OPENAI_API_KEY and not settings.GEMINI_API_KEY:
            errors.append("At least one AI API key is required")

    if errors:
        error_msg = "\n".join(f"  - {e}" for e in errors)
        raise ValueError(f"Configuration errors:\n{error_msg}")

    return True


# ==========================================================================
# EXPORTS
# ==========================================================================

__all__ = [
    "Settings",
    "DevelopmentSettings",
    "ProductionSettings",
    "TestSettings",
    "settings",
    "get_settings",
    "validate_settings",
]
