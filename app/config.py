"""Application settings, loaded and validated from the environment / .env.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application configuration.

    Field names map (case-insensitively) to keys in .env. Fields without a
    default are required — the app fails fast at startup if they're missing.
    """

    # --- Application ---
    APP_NAME: str = "Gym Equipment API"
    DEBUG: bool = False

    # --- Database (PostgreSQL) ---
    # Sync URL is used by Alembic; async URL (asyncpg) is used by the app.
    DATABASE_URL: str
    ASYNC_DATABASE_URL: str

    # --- Security / JWT ---
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # --- First admin (seeded on first run) ---
    FIRST_ADMIN_EMAIL: str
    FIRST_ADMIN_PASSWORD: str

    # --- Redis (equipment list caching) ---
    REDIS_URL: str = "redis://localhost:6379/0"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Cached accessor for use as a FastAPI dependency (`Depends(get_settings)`).

    The cache makes it a singleton at runtime while staying overridable in tests
    via `app.dependency_overrides`.
    """
    return Settings()


# Module-level singleton for direct imports (e.g. `from app.config import settings`).
settings = get_settings()
