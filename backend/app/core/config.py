"""Pydantic settings — loads from .env automatically."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # MongoDB
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db_name: str = "shopping_agent"

    # JWT
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 10080  # 7 days

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Google OAuth
    google_client_id: str = ""

    # eBay
    ebay_app_id: str = ""
    ebay_base_url: str = "https://svcs.ebay.com/services/search/FindingService/v1"

    # Rate limiting
    rate_limit_per_minute: int = 20

    # Cache
    cache_ttl_seconds: int = 3600

    # App
    app_env: str = "development"
    app_version: str = "1.0.0"
    debug: bool = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
