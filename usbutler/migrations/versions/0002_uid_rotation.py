"""Add per-user rotating UID credentials."""

from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa

revision = "0002_uid_rotation"
down_revision = "0001_legacy_schema"
branch_labels = None
depends_on = None


def _table_names(connection) -> set[str]:
    return set(sa.inspect(connection).get_table_names())


def _column_names(connection, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(connection).get_columns(table)}


def _index_names(connection, table: str) -> set[str]:
    if connection.dialect.name == "sqlite":
        return set(
            connection.execute(
                sa.text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'index' AND tbl_name = :table"
                ),
                {"table": table},
            ).scalars()
        )
    return {
        index["name"]
        for index in sa.inspect(connection).get_indexes(table)
        if index["name"]
    }


def _recover_interrupted_batch(connection) -> None:
    """Recover an Alembic SQLite batch table left by the original migration."""
    tables = _table_names(connection)
    temporary = "_alembic_tmp_identifiers"
    if temporary not in tables:
        return
    if "identifiers" in tables:
        op.drop_table(temporary)
    else:
        op.rename_table(temporary, "identifiers")


def _add_identifier_columns(connection) -> None:
    missing = {
        "chain_root_id",
        "predecessor_id",
        "reservation_id",
        "state",
        "generated_at",
        "confirmed_at",
        "last_write_attempt_at",
    } - _column_names(connection, "identifiers")
    if not missing:
        return

    if connection.dialect.name == "sqlite":
        # Nullable REFERENCES columns are supported by SQLite's ADD COLUMN and
        # avoid a table rebuild, whose DDL cannot be rolled back after failure.
        definitions = {
            "chain_root_id": ("INTEGER REFERENCES identifiers(id) ON DELETE CASCADE"),
            "predecessor_id": ("INTEGER REFERENCES identifiers(id) ON DELETE SET NULL"),
            "reservation_id": (
                "INTEGER REFERENCES uid_reservations(id) ON DELETE RESTRICT"
            ),
            "state": "VARCHAR(7) NOT NULL DEFAULT 'STATIC'",
            "generated_at": "DATETIME",
            "confirmed_at": "DATETIME",
            "last_write_attempt_at": "DATETIME",
        }
        for name, definition in definitions.items():
            if name in missing:
                op.execute(
                    sa.text(f"ALTER TABLE identifiers ADD COLUMN {name} {definition}")
                )
        return

    columns = {
        "chain_root_id": sa.Column(
            "chain_root_id",
            sa.Integer(),
            sa.ForeignKey("identifiers.id", ondelete="CASCADE"),
            nullable=True,
        ),
        "predecessor_id": sa.Column(
            "predecessor_id",
            sa.Integer(),
            sa.ForeignKey("identifiers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        "reservation_id": sa.Column(
            "reservation_id",
            sa.Integer(),
            sa.ForeignKey("uid_reservations.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        "state": sa.Column(
            "state",
            sa.Enum("STATIC", "CURRENT", "PENDING", "RETIRED", name="identifierstate"),
            nullable=False,
            server_default="STATIC",
        ),
        "generated_at": sa.Column("generated_at", sa.DateTime(), nullable=True),
        "confirmed_at": sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        "last_write_attempt_at": sa.Column(
            "last_write_attempt_at", sa.DateTime(), nullable=True
        ),
    }
    for name, column in columns.items():
        if name in missing:
            op.add_column("identifiers", column)


def _validate_identifier_values(connection) -> list[dict]:
    rows = list(
        connection.execute(
            sa.text("SELECT id, value, type FROM identifiers ORDER BY id")
        ).mappings()
    )
    final_values: dict[str, int] = {}
    collisions: list[tuple[int, int]] = []
    for row in rows:
        value = row["value"]
        if row["type"] == "UID":
            value = value.replace(" ", "").replace(":", "").upper()
        key = value.lower()
        if previous := final_values.get(key):
            collisions.append((previous, row["id"]))
        else:
            final_values[key] = row["id"]
    if collisions:
        pairs = ", ".join(f"{left}/{right}" for left, right in collisions)
        raise RuntimeError(
            "Cannot normalize duplicate identifier values; conflicting row IDs: "
            f"{pairs}"
        )
    return rows


def _backfill_uid_reservations(connection, rows: list[dict]) -> None:
    for row in rows:
        if row["type"] != "UID":
            continue
        normalized = row["value"].replace(" ", "").replace(":", "").upper()
        reservation_id = connection.execute(
            sa.text(
                "SELECT id FROM uid_reservations WHERE lower(value) = lower(:value)"
            ),
            {"value": normalized},
        ).scalar()
        if reservation_id is None:
            result = connection.execute(
                sa.text(
                    "INSERT INTO uid_reservations (value, created_at) "
                    "VALUES (:value, :created_at)"
                ),
                {
                    "value": normalized,
                    "created_at": datetime.now(UTC).replace(tzinfo=None),
                },
            )
            reservation_id = result.lastrowid
        connection.execute(
            sa.text(
                "UPDATE identifiers "
                "SET value = :value, reservation_id = :reservation_id "
                "WHERE id = :identifier_id"
            ),
            {
                "value": normalized,
                "reservation_id": reservation_id,
                "identifier_id": row["id"],
            },
        )


def _create_index_if_missing(
    connection,
    name: str,
    table: str,
    columns: list,
    **kwargs,
) -> None:
    if name not in _index_names(connection, table):
        op.create_index(name, table, columns, **kwargs)


def _ensure_attempt_table(connection) -> None:
    if "uid_rotation_attempts" not in _table_names(connection):
        op.create_table(
            "uid_rotation_attempts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "chain_root_id",
                sa.Integer(),
                sa.ForeignKey("identifiers.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "source_identifier_id",
                sa.Integer(),
                sa.ForeignKey("identifiers.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "target_reservation_id",
                sa.Integer(),
                sa.ForeignKey("uid_reservations.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("attempted_at", sa.DateTime(), nullable=False),
            sa.Column(
                "protocol",
                sa.Enum("UNKNOWN", "GEN1A", "GEN2", name="uidrotationprotocol"),
                nullable=False,
            ),
            sa.Column(
                "outcome",
                sa.Enum(
                    "STARTED",
                    "ACKNOWLEDGED",
                    "UNSUPPORTED",
                    "NAK",
                    "TIMEOUT",
                    "PCSC_ERROR",
                    "CONNECTION_LOSS",
                    "FAILED",
                    name="uidrotationoutcome",
                ),
                nullable=False,
            ),
            sa.Column("detail", sa.String(500), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        )
    for column in (
        "chain_root_id",
        "source_identifier_id",
        "target_reservation_id",
        "attempted_at",
    ):
        _create_index_if_missing(
            connection,
            f"ix_uid_rotation_attempts_{column}",
            "uid_rotation_attempts",
            [column],
        )


def upgrade() -> None:
    connection = op.get_bind()
    _recover_interrupted_batch(connection)

    if "uid_rotation_enabled" not in _column_names(connection, "users"):
        op.add_column(
            "users",
            sa.Column(
                "uid_rotation_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )
    # Every user present before the migration completes remains opt-in.
    op.execute(sa.text("UPDATE users SET uid_rotation_enabled = false"))

    if "uid_reservations" not in _table_names(connection):
        op.create_table(
            "uid_reservations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("value", sa.String(100), nullable=False, unique=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    _add_identifier_columns(connection)
    rows = _validate_identifier_values(connection)
    _backfill_uid_reservations(connection, rows)

    _create_index_if_missing(
        connection,
        "uq_uid_reservations_value_lower",
        "uid_reservations",
        [sa.text("lower(value)")],
        unique=True,
    )
    _create_index_if_missing(
        connection,
        "uq_identifiers_value_lower",
        "identifiers",
        [sa.text("lower(value)")],
        unique=True,
    )
    _create_index_if_missing(
        connection,
        "ix_identifiers_chain_root_id",
        "identifiers",
        ["chain_root_id"],
    )
    _create_index_if_missing(
        connection,
        "ix_identifiers_predecessor_id",
        "identifiers",
        ["predecessor_id"],
    )
    _create_index_if_missing(
        connection,
        "ix_identifiers_reservation_id",
        "identifiers",
        ["reservation_id"],
        unique=True,
    )
    _create_index_if_missing(
        connection,
        "ix_identifiers_state",
        "identifiers",
        ["state"],
    )
    _create_index_if_missing(
        connection,
        "uq_identifiers_current_per_chain",
        "identifiers",
        ["chain_root_id"],
        unique=True,
        sqlite_where=sa.text("state = 'CURRENT'"),
        postgresql_where=sa.text("state = 'CURRENT'"),
    )
    _ensure_attempt_table(connection)


def downgrade() -> None:
    op.drop_table("uid_rotation_attempts")
    for index in (
        "uq_identifiers_current_per_chain",
        "ix_identifiers_state",
        "ix_identifiers_reservation_id",
        "ix_identifiers_predecessor_id",
        "ix_identifiers_chain_root_id",
    ):
        op.drop_index(index, table_name="identifiers")
    for column in (
        "last_write_attempt_at",
        "confirmed_at",
        "generated_at",
        "state",
        "reservation_id",
        "predecessor_id",
        "chain_root_id",
    ):
        op.drop_column("identifiers", column)
    op.drop_table("uid_reservations")
    op.drop_column("users", "uid_rotation_enabled")
