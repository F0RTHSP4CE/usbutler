"""Migration tests for fresh and unversioned legacy SQLite databases."""

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

import app.migrations as migration_bootstrap


def config(project_dir, url: str) -> Config:
    result = Config(str(project_dir / "alembic.ini"))
    result.set_main_option("script_location", str(project_dir / "migrations"))
    result.set_main_option("sqlalchemy.url", url)
    return result


def test_fresh_database_migrates_to_data_rotation_schema(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'fresh.db'}"
    engine = create_engine(url)
    monkeypatch.setattr(migration_bootstrap, "engine", engine)
    monkeypatch.setattr(migration_bootstrap.settings, "DATABASE_URL", url)

    migration_bootstrap.run_migrations()

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"mifare_credentials", "mifare_uuid_values"} <= tables
    assert "uid_reservations" not in tables
    assert "uid_rotation_attempts" not in tables
    assert "mifare_rotation_enabled" in {
        column["name"] for column in inspector.get_columns("users")
    }
    identifier_columns = {
        column["name"] for column in inspector.get_columns("identifiers")
    }
    assert identifier_columns == {"id", "value", "type", "user_id"}

    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO users (username, status) VALUES ('future', 'ACTIVE')")
        )
        assert (
            connection.execute(
                text(
                    "SELECT mifare_rotation_enabled FROM users "
                    "WHERE username = 'future'"
                )
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            == "0002_mifare_data_rotation"
        )


def test_unversioned_legacy_database_is_stamped_and_preserved(tmp_path, monkeypatch):
    project_dir = migration_bootstrap.Path(__file__).resolve().parent.parent
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    command.upgrade(config(project_dir, url), "0001_legacy_schema")

    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, username, status, api_token_hash, api_allowed_sources) "
                "VALUES (1, 'legacy', 'ACTIVE', NULL, NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO identifiers (id, value, type, user_id) "
                "VALUES (1, '01:02:03:04', 'UID', 1)"
            )
        )
        connection.execute(text("DROP TABLE alembic_version"))

    monkeypatch.setattr(migration_bootstrap, "engine", engine)
    monkeypatch.setattr(migration_bootstrap.settings, "DATABASE_URL", url)
    migration_bootstrap.run_migrations()

    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT mifare_rotation_enabled FROM users WHERE id = 1")
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                text("SELECT value FROM identifiers WHERE id = 1")
            ).scalar_one()
            == "01:02:03:04"
        )
        assert (
            connection.execute(
                text("SELECT count(*) FROM mifare_credentials")
            ).scalar_one()
            == 0
        )
