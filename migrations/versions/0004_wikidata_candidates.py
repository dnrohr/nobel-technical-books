"""Create source record and field assertion tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_record",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_fetch_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_entity_type", sa.String(length=30), nullable=False),
        sa.Column("source_entity_id", sa.Text(), nullable=True),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["source_fetch_id"], ["source_fetch.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_fetch_id",
            "source",
            "source_entity_type",
            "source_entity_id",
            name="uq_source_record_fetch_entity",
        ),
    )
    op.create_index(op.f("ix_source_record_source"), "source_record", ["source"])
    op.create_index(
        op.f("ix_source_record_source_entity_type"),
        "source_record",
        ["source_entity_type"],
    )
    op.create_index(op.f("ix_source_record_source_fetch_id"), "source_record", ["source_fetch_id"])
    op.create_table(
        "assertion",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subject_type", sa.String(length=30), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("predicate", sa.String(length=50), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("value_hash", sa.String(length=64), nullable=False),
        sa.Column("source_record_id", sa.Integer(), nullable=False),
        sa.Column("reliability_class", sa.String(length=5), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("is_selected", sa.Boolean(), nullable=False),
        sa.Column("is_contradicted", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["source_record_id"], ["source_record.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_record_id",
            "subject_type",
            "subject_id",
            "predicate",
            "value_hash",
            name="uq_assertion_value",
        ),
    )
    op.create_index(op.f("ix_assertion_predicate"), "assertion", ["predicate"])
    op.create_index(op.f("ix_assertion_source_record_id"), "assertion", ["source_record_id"])
    op.create_index(op.f("ix_assertion_subject_id"), "assertion", ["subject_id"])
    op.create_index(op.f("ix_assertion_subject_type"), "assertion", ["subject_type"])


def downgrade() -> None:
    op.drop_index(op.f("ix_assertion_subject_type"), table_name="assertion")
    op.drop_index(op.f("ix_assertion_subject_id"), table_name="assertion")
    op.drop_index(op.f("ix_assertion_source_record_id"), table_name="assertion")
    op.drop_index(op.f("ix_assertion_predicate"), table_name="assertion")
    op.drop_table("assertion")
    op.drop_index(op.f("ix_source_record_source_fetch_id"), table_name="source_record")
    op.drop_index(op.f("ix_source_record_source_entity_type"), table_name="source_record")
    op.drop_index(op.f("ix_source_record_source"), table_name="source_record")
    op.drop_table("source_record")
