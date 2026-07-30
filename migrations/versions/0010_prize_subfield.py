"""Add optional research subfield to prize awards."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "prize_award",
        sa.Column("subfield", sa.String(length=100), nullable=True),
    )
    op.create_index(
        op.f("ix_prize_award_subfield"),
        "prize_award",
        ["subfield"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_prize_award_subfield"), table_name="prize_award")
    op.drop_column("prize_award", "subfield")
