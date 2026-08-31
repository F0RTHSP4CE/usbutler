"""Add the per-user UID write-throttle policy."""

from alembic import op
import sqlalchemy as sa

revision = "0003_uid_rotation_every_read"
down_revision = "0002_uid_rotation"
branch_labels = None
depends_on = None


def _column_names(connection, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(connection).get_columns(table)}


def upgrade() -> None:
    connection = op.get_bind()
    if "uid_rotation_every_read" not in _column_names(connection, "users"):
        op.add_column(
            "users",
            sa.Column(
                "uid_rotation_every_read",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    # Existing users retain the rolling 24-hour policy until an administrator
    # explicitly opts them into write-on-every-presentation behavior.
    op.execute(sa.text("UPDATE users SET uid_rotation_every_read = false"))


def downgrade() -> None:
    op.drop_column("users", "uid_rotation_every_read")
