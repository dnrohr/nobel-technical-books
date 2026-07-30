"""Create scored laureate contribution table."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contribution",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("laureate_id", sa.Integer(), nullable=False),
        sa.Column("canonical_work_id", sa.Integer(), nullable=True),
        sa.Column("edition_id", sa.Integer(), nullable=True),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("credited_name", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("relationship_confidence", sa.Float(), nullable=False),
        sa.Column("review_status", sa.String(length=30), nullable=False),
        sa.Column("is_default_included", sa.Boolean(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["canonical_work_id"], ["canonical_work.id"]),
        sa.ForeignKeyConstraint(["edition_id"], ["edition.id"]),
        sa.ForeignKeyConstraint(["laureate_id"], ["laureate.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "laureate_id",
            "canonical_work_id",
            "edition_id",
            "role",
            name="uq_contribution_target_role",
        ),
    )
    for column in (
        "canonical_work_id",
        "edition_id",
        "is_default_included",
        "laureate_id",
        "relationship_confidence",
        "review_status",
        "role",
    ):
        op.create_index(op.f(f"ix_contribution_{column}"), "contribution", [column])


def downgrade() -> None:
    for column in (
        "role",
        "review_status",
        "relationship_confidence",
        "laureate_id",
        "is_default_included",
        "edition_id",
        "canonical_work_id",
    ):
        op.drop_index(op.f(f"ix_contribution_{column}"), table_name="contribution")
    op.drop_table("contribution")
