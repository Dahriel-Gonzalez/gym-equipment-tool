"""Application settings, loaded and validated from the environment / .env.
"""
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import model_validator
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
    # DATABASE_URL is the plain postgresql:// string (what a managed provider
    # like Render exposes). ASYNC_DATABASE_URL is the asyncpg variant used by the
    # app engine and Alembic; if it's left unset it's derived from DATABASE_URL by
    # swapping in the asyncpg driver, so a single provided URL is enough. Set both
    # explicitly in local .env when they point at different hosts/ports.
    DATABASE_URL: str
    ASYNC_DATABASE_URL: str = ""

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

    @model_validator(mode="after")
    def _derive_async_database_url(self) -> "Settings":
        """Fill ASYNC_DATABASE_URL from DATABASE_URL when it isn't set explicitly.

        Managed Postgres (e.g. Render) hands out one `postgresql://` URL; the app
        needs the `postgresql+asyncpg://` form. We rewrite the scheme so a single
        env var is enough in production.
        """
        if not self.ASYNC_DATABASE_URL:
            url = self.DATABASE_URL
            for prefix in ("postgresql://", "postgres://"):
                if url.startswith(prefix):
                    url = "postgresql+asyncpg://" + url[len(prefix):]
                    break
            # asyncpg doesn't understand libpq's sslmode / channel_binding query
            # params (Neon and most managed Postgres append them). Strip them here
            # and turn TLS on via the engine's connect_args instead — see
            # db_ssl_required below.
            parts = urlsplit(url)
            kept = [
                (k, v)
                for k, v in parse_qsl(parts.query)
                if k not in ("sslmode", "channel_binding")
            ]
            self.ASYNC_DATABASE_URL = urlunsplit(parts._replace(query=urlencode(kept)))
        return self

    @property
    def db_ssl_required(self) -> bool:
        """True when the source URL asked for TLS (e.g. Neon's `sslmode=require`).

        asyncpg can't read libpq's sslmode, so the engine passes `ssl=True` in
        connect_args when this is set. Local Docker Postgres has no sslmode, so
        this stays False and we connect in plaintext as before.
        """
        url = self.DATABASE_URL.lower()
        return "sslmode=require" in url or "sslmode=verify" in url

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
