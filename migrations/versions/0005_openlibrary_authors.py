"""Create source author candidate table."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_author_candidate",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("laureate_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_author_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("source_fetch_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["laureate_id"], ["laureate.id"]),
        sa.ForeignKeyConstraint(["source_fetch_id"], ["source_fetch.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "laureate_id",
            "source",
            "source_author_id",
            name="uq_source_author_candidate",
        ),
    )
    op.create_index(
        op.f("ix_source_author_candidate_laureate_id"),
        "source_author_candidate",
        ["laureate_id"],
    )
    op.create_index(
        op.f("ix_source_author_candidate_source"),
        "source_author_candidate",
        ["source"],
    )
    op.create_index(
        op.f("ix_source_author_candidate_status"),
        "source_author_candidate",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_source_author_candidate_status"), table_name="source_author_candidate")
    op.drop_index(op.f("ix_source_author_candidate_source"), table_name="source_author_candidate")
    op.drop_index(
        op.f("ix_source_author_candidate_laureate_id"),
        table_name="source_author_candidate",
    )
    op.drop_table("source_author_candidate")
