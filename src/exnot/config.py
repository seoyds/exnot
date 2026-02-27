from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://exnot:exnot_dev_password@localhost:5432/exnot"
    database_url_sync: str = "postgresql+psycopg2://exnot:exnot_dev_password@localhost:5432/exnot"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Anthropic
    anthropic_api_key: str = ""

    # Email (Gmail SMTP)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    email_from: str = ""
    email_from_name: str = "ExNot Fee Alerts"

    # Application
    secret_key: str = "change-this-to-a-random-secret-key"
    app_url: str = "http://localhost:8000"
    log_level: str = "INFO"

    # Admin
    admin_email: str = "admin@example.com"
    admin_password: str = "changeme"

    # MinIO (S3-compatible object storage)
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "exnot"
    minio_secret_key: str = "exnot_dev_password"
    minio_bucket: str = "exnot-documents"
    minio_secure: bool = False

    # Scraping
    scrape_delay_seconds: float = Field(default=3.0, description="Delay between requests to same domain")
    scrape_max_retries: int = 3
    scrape_timeout_seconds: int = 30
    user_agent: str = "ExNot/0.1.0 (US Options Fee Schedule Monitor; +https://github.com/exnot)"

    # AI
    ai_model: str = "claude-sonnet-4-6"
    ai_max_tokens: int = 8192
    ai_confidence_threshold: float = 0.8
    ai_max_retries: int = 3

    # URL Discovery
    serpapi_api_key: str = ""
    discovery_max_candidates: int = 15
    discovery_fetch_timeout: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()
