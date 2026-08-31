"""Add per-fob MIFARE data-block UUID credentials."""

from alembic import op
import sqlalchemy as sa

revision = "0002_mifare_data_rotation"
down_revision = "0001_legacy_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "mifare_rotation_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Rotation is opt-in for every user, including rows created before Alembic.
    op.execute(sa.text("UPDATE users SET mifare_rotation_enabled = false"))

    op.create_table(
        "mifare_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "identifier_id",
            sa.Integer(),
            sa.ForeignKey("identifiers.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("last_verified_rotation_at", sa.DateTime(), nullable=True),
        sa.Column("last_write_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_write_error", sa.String(500), nullable=True),
    )
    op.create_index(
        "ix_mifare_credentials_identifier_id",
        "mifare_credentials",
        ["identifier_id"],
        unique=True,
    )

    op.create_table(
        "mifare_uuid_values",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "credential_id",
            sa.Integer(),
            sa.ForeignKey("mifare_credentials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("value", sa.String(36), nullable=False, unique=True),
        sa.Column(
            "state",
            sa.Enum("PENDING", "CONFIRMED", name="mifareuuidstate"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_mifare_uuid_values_credential_id",
        "mifare_uuid_values",
        ["credential_id"],
    )
    op.create_index("ix_mifare_uuid_values_state", "mifare_uuid_values", ["state"])
    op.create_index(
        "uq_mifare_uuid_values_value_lower",
        "mifare_uuid_values",
        [sa.text("lower(value)")],
        unique=True,
    )
    op.create_index(
        "uq_mifare_uuid_values_pending_per_credential",
        "mifare_uuid_values",
        ["credential_id"],
        unique=True,
        sqlite_where=sa.text("state = 'PENDING'"),
        postgresql_where=sa.text("state = 'PENDING'"),
    )


def downgrade() -> None:
    op.drop_table("mifare_uuid_values")
    op.drop_table("mifare_credentials")
    op.drop_column("users", "mifare_rotation_enabled")
