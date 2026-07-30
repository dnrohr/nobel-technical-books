"""Create authority identity and name variant tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_identity",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("laureate_id", sa.Integer(), nullable=False),
        sa.Column("scheme", sa.String(length=40), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=True),
        sa.Column("resolution_status", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["laureate_id"], ["laureate.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scheme", "value", name="uq_external_identity"),
    )
    op.create_index(op.f("ix_external_identity_laureate_id"), "external_identity", ["laureate_id"])
    op.create_index(
        op.f("ix_external_identity_resolution_status"),
        "external_identity",
        ["resolution_status"],
    )
    op.create_index(op.f("ix_external_identity_scheme"), "external_identity", ["scheme"])
    op.create_table(
        "person_name_variant",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("laureate_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=True),
        sa.Column("script", sa.String(length=30), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("is_preferred", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["laureate_id"], ["laureate.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("laureate_id", "name", "source", name="uq_person_name_variant"),
    )
    op.create_index(
        op.f("ix_person_name_variant_laureate_id"),
        "person_name_variant",
        ["laureate_id"],
    )
    op.create_index(
        op.f("ix_person_name_variant_normalized_name"),
        "person_name_variant",
        ["normalized_name"],
    )
    op.create_table(
        "identity_resolution",
        sa.Column("laureate_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("candidate_qids", sa.JSON(), nullable=False),
        sa.Column("source_fetch_id", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["laureate_id"], ["laureate.id"]),
        sa.ForeignKeyConstraint(["source_fetch_id"], ["source_fetch.id"]),
        sa.PrimaryKeyConstraint("laureate_id"),
    )
    op.create_index(op.f("ix_identity_resolution_status"), "identity_resolution", ["status"])


def downgrade() -> None:
    op.drop_index(op.f("ix_identity_resolution_status"), table_name="identity_resolution")
    op.drop_table("identity_resolution")
    op.drop_index(
        op.f("ix_person_name_variant_normalized_name"),
        table_name="person_name_variant",
    )
    op.drop_index(op.f("ix_person_name_variant_laureate_id"), table_name="person_name_variant")
    op.drop_table("person_name_variant")
    op.drop_index(op.f("ix_external_identity_scheme"), table_name="external_identity")
    op.drop_index(op.f("ix_external_identity_resolution_status"), table_name="external_identity")
    op.drop_index(op.f("ix_external_identity_laureate_id"), table_name="external_identity")
    op.drop_table("external_identity")
