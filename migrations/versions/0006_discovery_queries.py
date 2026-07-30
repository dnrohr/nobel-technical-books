"""Create controlled discovery query log."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discovery_query",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("laureate_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("variant_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["laureate_id"], ["laureate.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("laureate_id", "source", "query_text", name="uq_discovery_query"),
    )
    op.create_index(op.f("ix_discovery_query_laureate_id"), "discovery_query", ["laureate_id"])
    op.create_index(op.f("ix_discovery_query_source"), "discovery_query", ["source"])


def downgrade() -> None:
    op.drop_index(op.f("ix_discovery_query_source"), table_name="discovery_query")
    op.drop_index(op.f("ix_discovery_query_laureate_id"), table_name="discovery_query")
    op.drop_table("discovery_query")
