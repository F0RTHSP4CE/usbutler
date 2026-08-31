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
    assert "uid_rotation_every_read" in {
        column["name"] for column in inspect(engine).get_columns("users")
    }
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO users (username, status) VALUES ('future', 'ACTIVE')")
        )
        enabled, every_read = connection.execute(
            text(
                "SELECT uid_rotation_enabled, uid_rotation_every_read "
                "FROM users WHERE username = 'future'"
            )
        ).one()
    assert enabled == 1
    assert every_read == 0


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
            text(
                "SELECT uid_rotation_enabled, uid_rotation_every_read "
                "FROM users WHERE id = 1"
            )
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
    assert user.uid_rotation_every_read == 0
    assert identifier.value == "01020304"
    assert identifier.state == "STATIC"
    assert identifier.chain_root_id is None
    assert identifier.reservation_id is not None
    assert reservations == ["01020304"]


def test_recover_partially_applied_deployed_sqlite_schema(tmp_path, monkeypatch):
    """Recover the exact state left when the legacy lowercase index is absent."""
    project_dir = migration_bootstrap.Path(__file__).resolve().parent.parent
    url = f"sqlite:///{tmp_path / 'partial.db'}"
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
        connection.execute(text("DROP INDEX uq_identifiers_value_lower"))
        # This ALTER persisted on the deployed SQLite volume before the old
        # migration failed while trying to drop the already-missing index.
        connection.execute(
            text(
                "ALTER TABLE users ADD COLUMN uid_rotation_enabled "
                "BOOLEAN NOT NULL DEFAULT 1"
            )
        )

    monkeypatch.setattr(migration_bootstrap, "engine", engine)
    monkeypatch.setattr(migration_bootstrap.settings, "DATABASE_URL", url)
    migration_bootstrap.run_migrations()

    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            == "0003_uid_rotation_every_read"
        )
        assert (
            connection.execute(
                text("SELECT uid_rotation_enabled FROM users WHERE id = 1")
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                text("SELECT uid_rotation_every_read FROM users WHERE id = 1")
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                text("SELECT value FROM identifiers WHERE id = 1")
            ).scalar_one()
            == "01020304"
        )
        assert (
            connection.execute(
                text("SELECT count(*) FROM uid_reservations")
            ).scalar_one()
            == 1
        )
        assert "uid_rotation_attempts" in inspect(engine).get_table_names()
        assert {
            "chain_root_id",
            "predecessor_id",
            "reservation_id",
            "state",
            "generated_at",
            "confirmed_at",
            "last_write_attempt_at",
        } <= {column["name"] for column in inspect(engine).get_columns("identifiers")}

    # A crash after all SQLite DDL but before Alembic records the revision must
    # also be recoverable without duplicating reservations or indexes.
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE alembic_version SET version_num = '0001_legacy_schema'")
        )
    migration_bootstrap.run_migrations()
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            == "0003_uid_rotation_every_read"
        )
        assert (
            connection.execute(
                text("SELECT count(*) FROM uid_reservations")
            ).scalar_one()
            == 1
        )
