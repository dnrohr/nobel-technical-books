"""Create canonical work, hierarchy, review, and manual override tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "canonical_work",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cluster_key", sa.String(length=64), nullable=False),
        sa.Column("preferred_title", sa.Text(), nullable=False),
        sa.Column("normalized_title", sa.Text(), nullable=False),
        sa.Column("original_title", sa.Text(), nullable=True),
        sa.Column("original_language", sa.String(length=30), nullable=True),
        sa.Column("first_publication_year", sa.Integer(), nullable=True),
        sa.Column("work_type", sa.String(length=40), nullable=False),
        sa.Column("technicality_score", sa.Float(), nullable=True),
        sa.Column("audience_level", sa.String(length=30), nullable=True),
        sa.Column("classification_confidence", sa.Float(), nullable=True),
        sa.Column("classification_method", sa.String(length=40), nullable=True),
        sa.Column("classification_reason", sa.Text(), nullable=True),
        sa.Column("series_title", sa.Text(), nullable=True),
        sa.Column("volume_designation", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("review_status", sa.String(length=30), nullable=False),
        sa.Column("overall_confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "cluster_key",
        "first_publication_year",
        "normalized_title",
        "review_status",
        "work_type",
    ):
        op.create_index(
            op.f(f"ix_canonical_work_{column}"),
            "canonical_work",
            [column],
            unique=column == "cluster_key",
        )
    op.create_table(
        "manual_override",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_key", sa.Text(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("reviewer", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supersedes_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["supersedes_id"], ["manual_override.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "target_type", "target_key", "action", name="uq_manual_override_action"
        ),
    )
    op.create_index(op.f("ix_manual_override_action"), "manual_override", ["action"])
    op.create_index(op.f("ix_manual_override_target_type"), "manual_override", ["target_type"])
    op.create_table(
        "work_merge_proposal",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("left_work_id", sa.Integer(), nullable=False),
        sa.Column("right_work_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["left_work_id"], ["canonical_work.id"]),
        sa.ForeignKeyConstraint(["right_work_id"], ["canonical_work.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("left_work_id", "right_work_id", "status", name="uq_work_review_pair"),
    )
    op.create_index(op.f("ix_work_merge_proposal_status"), "work_merge_proposal", ["status"])
    op.create_table(
        "work_relation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("parent_work_id", sa.Integer(), nullable=False),
        sa.Column("child_work_id", sa.Integer(), nullable=False),
        sa.Column("relation_type", sa.String(length=30), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["child_work_id"], ["canonical_work.id"]),
        sa.ForeignKeyConstraint(["parent_work_id"], ["canonical_work.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "parent_work_id", "child_work_id", "relation_type", name="uq_work_relation"
        ),
    )
    op.create_table(
        "work_source_record",
        sa.Column("source_record_id", sa.Integer(), nullable=False),
        sa.Column("canonical_work_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["canonical_work_id"], ["canonical_work.id"]),
        sa.ForeignKeyConstraint(["source_record_id"], ["source_record.id"]),
        sa.PrimaryKeyConstraint("source_record_id"),
    )
    op.create_index(
        op.f("ix_work_source_record_canonical_work_id"),
        "work_source_record",
        ["canonical_work_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_work_source_record_canonical_work_id"),
        table_name="work_source_record",
    )
    op.drop_table("work_source_record")
    op.drop_table("work_relation")
    op.drop_index(op.f("ix_work_merge_proposal_status"), table_name="work_merge_proposal")
    op.drop_table("work_merge_proposal")
    op.drop_index(op.f("ix_manual_override_target_type"), table_name="manual_override")
    op.drop_index(op.f("ix_manual_override_action"), table_name="manual_override")
    op.drop_table("manual_override")
    for column in (
        "work_type",
        "review_status",
        "normalized_title",
        "first_publication_year",
        "cluster_key",
    ):
        op.drop_index(op.f(f"ix_canonical_work_{column}"), table_name="canonical_work")
    op.drop_table("canonical_work")
