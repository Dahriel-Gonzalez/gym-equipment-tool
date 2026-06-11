"""Alembic environment — async (asyncpg) configuration.

Reads the database URL from the environment (ASYNC_DATABASE_URL), targets
Base.metadata, and runs migrations through an async engine. Once app/config.py
exists you can swap get_url() for `from app.config import settings`.
"""
import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# Load .env so the URL is available when running `alembic` from the CLI.
# Optional dependency — if python-dotenv isn't installed, rely on real env vars.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# Import the models package for its side effect: every model registers on
# Base.metadata, which is what autogenerate diffs against.
from app.db.base import Base
import app.models  # noqa: F401  (registers all tables)

# Alembic Config object — provides access to values in alembic.ini.
config = context.config

# Set up loggers from the .ini file.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    # Use the app's settings so ASYNC_DATABASE_URL is derived from DATABASE_URL
    # when only the latter is set (e.g. on Render). Falls back to the raw env var
    # if config can't be imported for some reason.
    try:
        from app.config import settings

        return settings.ASYNC_DATABASE_URL
    except Exception:
        url = os.getenv("ASYNC_DATABASE_URL")
        if not url:
            raise RuntimeError(
                "ASYNC_DATABASE_URL is not set. Copy .env.example to .env and fill it in."
            )
        return url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a DB connection (`alembic upgrade --sql`)."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations via run_sync."""
    # Mirror the app engine: managed Postgres (Neon) needs TLS via connect_args,
    # since asyncpg can't read the sslmode query param config.py strips off.
    connect_args = {}
    try:
        from app.config import settings

        if settings.db_ssl_required:
            connect_args["ssl"] = True
    except Exception:
        pass
    connectable = create_async_engine(
        get_url(), poolclass=pool.NullPool, connect_args=connect_args
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
