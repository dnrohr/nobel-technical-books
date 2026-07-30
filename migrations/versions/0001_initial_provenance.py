"""Create initial pipeline and source fetch tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pipeline_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile", sa.String(length=50), nullable=False),
        sa.Column(
            "status",
            sa.Enum("RUNNING", "SUCCEEDED", "FAILED", name="pipelinestatus", native_enum=False),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "source_fetch",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pipeline_run_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("request_url", sa.Text(), nullable=False),
        sa.Column("request_key", sa.String(length=64), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("cache_path", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_run.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source", "request_key", "content_hash", name="uq_source_fetch_payload"
        ),
    )
    op.create_index(op.f("ix_source_fetch_request_key"), "source_fetch", ["request_key"])
    op.create_index(op.f("ix_source_fetch_source"), "source_fetch", ["source"])


def downgrade() -> None:
    op.drop_index(op.f("ix_source_fetch_source"), table_name="source_fetch")
    op.drop_index(op.f("ix_source_fetch_request_key"), table_name="source_fetch")
    op.drop_table("source_fetch")
    op.drop_table("pipeline_run")
