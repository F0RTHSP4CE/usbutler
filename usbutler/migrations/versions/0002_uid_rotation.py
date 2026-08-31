"""Add per-user rotating UID credentials."""

from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa

revision = "0002_uid_rotation"
down_revision = "0001_legacy_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "uid_rotation_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    # The database default is enabled for users created after this migration,
    # while every user already present in a legacy volume remains opt-in.
    op.execute(sa.text("UPDATE users SET uid_rotation_enabled = false"))

    op.create_table(
        "uid_reservations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("value", sa.String(100), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "uq_uid_reservations_value_lower",
        "uid_reservations",
        [sa.text("lower(value)")],
        unique=True,
    )

    # SQLite cannot add foreign keys with ALTER TABLE. Batch mode rebuilds only
    # this table and preserves all legacy rows.
    op.drop_index("uq_identifiers_value_lower", table_name="identifiers")
    with op.batch_alter_table(
        "identifiers",
        recreate="always",
        naming_convention={
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
        },
    ) as batch_op:
        batch_op.add_column(
            sa.Column(
                "chain_root_id",
                sa.Integer(),
                sa.ForeignKey(
                    "identifiers.id",
                    name="fk_identifiers_chain_root_id",
                    ondelete="CASCADE",
                ),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "predecessor_id",
                sa.Integer(),
                sa.ForeignKey(
                    "identifiers.id",
                    name="fk_identifiers_predecessor_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "reservation_id",
                sa.Integer(),
                sa.ForeignKey(
                    "uid_reservations.id",
                    name="fk_identifiers_reservation_id",
                    ondelete="RESTRICT",
                ),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "state",
                sa.Enum(
                    "STATIC", "CURRENT", "PENDING", "RETIRED", name="identifierstate"
                ),
                nullable=False,
                server_default="STATIC",
            )
        )
        batch_op.add_column(sa.Column("generated_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("confirmed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column("last_write_attempt_at", sa.DateTime(), nullable=True)
        )
    op.create_index(
        "uq_identifiers_value_lower",
        "identifiers",
        [sa.text("lower(value)")],
        unique=True,
    )
    op.create_index("ix_identifiers_chain_root_id", "identifiers", ["chain_root_id"])
    op.create_index("ix_identifiers_predecessor_id", "identifiers", ["predecessor_id"])
    op.create_index(
        "ix_identifiers_reservation_id", "identifiers", ["reservation_id"], unique=True
    )
    op.create_index("ix_identifiers_state", "identifiers", ["state"])
    op.create_index(
        "uq_identifiers_current_per_chain",
        "identifiers",
        ["chain_root_id"],
        unique=True,
        sqlite_where=sa.text("state = 'CURRENT'"),
        postgresql_where=sa.text("state = 'CURRENT'"),
    )

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
        op.create_index(
            f"ix_uid_rotation_attempts_{column}",
            "uid_rotation_attempts",
            [column],
        )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, value FROM identifiers WHERE type = 'UID'")
    ).mappings()
    for row in rows:
        normalized = row["value"].replace(" ", "").replace(":", "").upper()
        existing = connection.execute(
            sa.text(
                "SELECT id FROM uid_reservations WHERE lower(value) = lower(:value)"
            ),
            {"value": normalized},
        ).scalar()
        if existing is None:
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
            existing = result.lastrowid
        connection.execute(
            sa.text(
                "UPDATE identifiers SET value = :value, reservation_id = :reservation_id "
                "WHERE id = :identifier_id"
            ),
            {
                "value": normalized,
                "reservation_id": existing,
                "identifier_id": row["id"],
            },
        )


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
