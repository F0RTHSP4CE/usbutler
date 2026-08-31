"""Managed schema migration bootstrap for fresh and legacy databases."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.config import settings
from app.database import engine

LEGACY_REVISION = "0001_legacy_schema"


def run_migrations() -> None:
    project_dir = Path(__file__).resolve().parent.parent
    config = Config(str(project_dir / "alembic.ini"))
    config.set_main_option("script_location", str(project_dir / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))

    tables = set(inspect(engine).get_table_names())
    if "alembic_version" not in tables and "users" in tables:
        command.stamp(config, LEGACY_REVISION)
    command.upgrade(config, "head")
