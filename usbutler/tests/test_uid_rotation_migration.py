"""Migration tests for fresh and unversioned legacy SQLite databases."""

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

import app.migrations as migration_bootstrap


def _config(project_dir, url: str) -> Config:
    config = Config(str(project_dir / "alembic.ini"))
    config.set_main_option("script_location", str(project_dir / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def test_fresh_database_migrates_to_rotation_schema(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'fresh.db'}"
    engine = create_engine(url)
    monkeypatch.setattr(migration_bootstrap, "engine", engine)
    monkeypatch.setattr(migration_bootstrap.settings, "DATABASE_URL", url)

    migration_bootstrap.run_migrations()

    tables = set(inspect(engine).get_table_names())
    assert {"uid_reservations", "uid_rotation_attempts"} <= tables
    assert "uid_rotation_enabled" in {
        column["name"] for column in inspect(engine).get_columns("users")
    }
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO users (username, status) VALUES ('future', 'ACTIVE')")
        )
        enabled = connection.execute(
            text("SELECT uid_rotation_enabled FROM users WHERE username = 'future'")
        ).scalar_one()
    assert enabled == 1


def test_unversioned_legacy_database_is_stamped_and_users_stay_disabled(
    tmp_path, monkeypatch
):
    project_dir = migration_bootstrap.Path(__file__).resolve().parent.parent
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    config = _config(project_dir, url)
    command.upgrade(config, "0001_legacy_schema")

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
        user = connection.execute(
            text("SELECT uid_rotation_enabled FROM users WHERE id = 1")
        ).one()
        identifier = connection.execute(
            text(
                "SELECT value, state, chain_root_id, reservation_id "
                "FROM identifiers WHERE id = 1"
            )
        ).one()
        reservations = (
            connection.execute(text("SELECT value FROM uid_reservations"))
            .scalars()
            .all()
        )

    assert user.uid_rotation_enabled == 0
    assert identifier.value == "01020304"
    assert identifier.state == "STATIC"
    assert identifier.chain_root_id is None
    assert identifier.reservation_id is not None
    assert reservations == ["01020304"]
