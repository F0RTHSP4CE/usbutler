"""Track the last successful use of each identifier."""

from alembic import op
import sqlalchemy as sa

revision = "0003_identifier_last_used"
down_revision = "0002_mifare_data_rotation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "identifiers",
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("identifiers", "last_used_at")
