"""Create laureate and prize award tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "laureate",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nobel_api_id", sa.String(length=30), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("given_name", sa.Text(), nullable=True),
        sa.Column("family_name", sa.Text(), nullable=True),
        sa.Column("full_name_native", sa.Text(), nullable=True),
        sa.Column("gender", sa.String(length=30), nullable=True),
        sa.Column("birth_date_raw", sa.String(length=30), nullable=True),
        sa.Column("death_date_raw", sa.String(length=30), nullable=True),
        sa.Column("is_organization", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_laureate_nobel_api_id"), "laureate", ["nobel_api_id"], unique=True)
    op.create_table(
        "prize_award",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("laureate_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("motivation", sa.Text(), nullable=True),
        sa.Column("share", sa.String(length=20), nullable=True),
        sa.Column("source_fetch_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["laureate_id"], ["laureate.id"]),
        sa.ForeignKeyConstraint(["source_fetch_id"], ["source_fetch.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("laureate_id", "category", "year", name="uq_laureate_prize"),
    )
    op.create_index(op.f("ix_prize_award_category"), "prize_award", ["category"])
    op.create_index(op.f("ix_prize_award_laureate_id"), "prize_award", ["laureate_id"])
    op.create_index(op.f("ix_prize_award_year"), "prize_award", ["year"])


def downgrade() -> None:
    op.drop_index(op.f("ix_prize_award_year"), table_name="prize_award")
    op.drop_index(op.f("ix_prize_award_laureate_id"), table_name="prize_award")
    op.drop_index(op.f("ix_prize_award_category"), table_name="prize_award")
    op.drop_table("prize_award")
    op.drop_index(op.f("ix_laureate_nobel_api_id"), table_name="laureate")
    op.drop_table("laureate")
