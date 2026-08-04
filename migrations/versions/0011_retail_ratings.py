"""Add reviewed retailer rating observations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "retail_rating_observation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("edition_id", sa.Integer(), nullable=False),
        sa.Column("retailer", sa.String(length=30), nullable=False),
        sa.Column("marketplace", sa.String(length=100), nullable=False),
        sa.Column("product_id", sa.String(length=30), nullable=False),
        sa.Column("average_rating", sa.Float(), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("match_confidence", sa.Float(), nullable=False),
        sa.Column("reviewer", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(["edition_id"], ["edition.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "edition_id",
            "retailer",
            "marketplace",
            "product_id",
            "observed_at",
            name="uq_retail_rating_observation",
        ),
    )
    op.create_index(
        op.f("ix_retail_rating_observation_edition_id"),
        "retail_rating_observation",
        ["edition_id"],
    )
    op.create_index(
        op.f("ix_retail_rating_observation_marketplace"),
        "retail_rating_observation",
        ["marketplace"],
    )
    op.create_index(
        op.f("ix_retail_rating_observation_observed_at"),
        "retail_rating_observation",
        ["observed_at"],
    )
    op.create_index(
        op.f("ix_retail_rating_observation_product_id"),
        "retail_rating_observation",
        ["product_id"],
    )
    op.create_index(
        op.f("ix_retail_rating_observation_retailer"),
        "retail_rating_observation",
        ["retailer"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_retail_rating_observation_retailer"),
        table_name="retail_rating_observation",
    )
    op.drop_index(
        op.f("ix_retail_rating_observation_product_id"),
        table_name="retail_rating_observation",
    )
    op.drop_index(
        op.f("ix_retail_rating_observation_observed_at"),
        table_name="retail_rating_observation",
    )
    op.drop_index(
        op.f("ix_retail_rating_observation_marketplace"),
        table_name="retail_rating_observation",
    )
    op.drop_index(
        op.f("ix_retail_rating_observation_edition_id"),
        table_name="retail_rating_observation",
    )
    op.drop_table("retail_rating_observation")
