"""Create the schema that predates managed migrations."""

from alembic import op
import sqlalchemy as sa

revision = "0001_legacy_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column(
            "status", sa.Enum("ACTIVE", "INACTIVE", name="userstatus"), nullable=False
        ),
        sa.Column("api_token_hash", sa.String(64), nullable=True),
        sa.Column("api_allowed_sources", sa.String(500), nullable=True),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "doors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("gpio_pin", sa.Integer(), nullable=False),
        sa.Column("gpio_active_low", sa.Boolean(), nullable=False),
        sa.Column("open_hold_time", sa.Float(), nullable=False),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_doors_id", "doors", ["id"])
    op.create_index("ix_doors_name", "doors", ["name"], unique=True)

    op.create_table(
        "identifiers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("value", sa.String(100), nullable=False),
        sa.Column("type", sa.Enum("PAN", "UID", name="identifiertype"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.UniqueConstraint("value"),
    )
    op.create_index("ix_identifiers_id", "identifiers", ["id"])
    op.create_index("ix_identifiers_value", "identifiers", ["value"], unique=True)
    op.create_index(
        "uq_identifiers_value_lower",
        "identifiers",
        [sa.text("lower(value)")],
        unique=True,
    )

    op.create_table(
        "door_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "door_id",
            sa.Integer(),
            sa.ForeignKey("doors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "event_type",
            sa.Enum("API", "BUTTON", "CARD", name="dooreventtype"),
            nullable=False,
        ),
        sa.Column("username", sa.String(100), nullable=True),
        sa.Column("on_behalf_of", sa.String(100), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
    )
    for column in ("id", "door_id", "user_id", "timestamp"):
        op.create_index(f"ix_door_events_{column}", "door_events", [column])


def downgrade() -> None:
    op.drop_table("door_events")
    op.drop_table("identifiers")
    op.drop_table("doors")
    op.drop_table("users")
