"""Create normalized edition reconciliation tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "edition",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cluster_key", sa.String(length=64), nullable=False),
        sa.Column("canonical_work_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("subtitle", sa.Text(), nullable=True),
        sa.Column("normalized_title", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=30), nullable=True),
        sa.Column("publication_date_raw", sa.Text(), nullable=True),
        sa.Column("publication_year", sa.Integer(), nullable=True),
        sa.Column("edition_statement", sa.Text(), nullable=True),
        sa.Column("publisher", sa.Text(), nullable=True),
        sa.Column("publication_place", sa.Text(), nullable=True),
        sa.Column("format", sa.String(length=40), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("isbn10", sa.String(length=10), nullable=True),
        sa.Column("isbn13", sa.String(length=13), nullable=True),
        sa.Column("doi", sa.Text(), nullable=True),
        sa.Column("oclc", sa.Text(), nullable=True),
        sa.Column("wikidata_qid", sa.Text(), nullable=True),
        sa.Column("openlibrary_edition_id", sa.Text(), nullable=True),
        sa.Column("google_books_id", sa.Text(), nullable=True),
        sa.Column("review_status", sa.String(length=30), nullable=False),
        sa.Column("overall_confidence", sa.Float(), nullable=False),
        sa.Column("merge_method", sa.String(length=40), nullable=False),
        sa.Column("identifier_issues", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "canonical_work_id",
        "cluster_key",
        "doi",
        "google_books_id",
        "isbn10",
        "isbn13",
        "normalized_title",
        "oclc",
        "openlibrary_edition_id",
        "publication_year",
        "review_status",
        "wikidata_qid",
    ):
        op.create_index(
            op.f(f"ix_edition_{column}"),
            "edition",
            [column],
            unique=column == "cluster_key",
        )
    op.create_table(
        "edition_merge_proposal",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("left_source_record_id", sa.Integer(), nullable=False),
        sa.Column("right_source_record_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("conflicts_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["left_source_record_id"], ["source_record.id"]),
        sa.ForeignKeyConstraint(["right_source_record_id"], ["source_record.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "left_source_record_id",
            "right_source_record_id",
            name="uq_edition_merge_pair",
        ),
    )
    for column in (
        "confidence",
        "left_source_record_id",
        "right_source_record_id",
        "status",
    ):
        op.create_index(
            op.f(f"ix_edition_merge_proposal_{column}"),
            "edition_merge_proposal",
            [column],
        )
    op.create_table(
        "edition_source_record",
        sa.Column("source_record_id", sa.Integer(), nullable=False),
        sa.Column("edition_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["edition_id"], ["edition.id"]),
        sa.ForeignKeyConstraint(["source_record_id"], ["source_record.id"]),
        sa.PrimaryKeyConstraint("source_record_id"),
    )
    op.create_index(
        op.f("ix_edition_source_record_edition_id"),
        "edition_source_record",
        ["edition_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_edition_source_record_edition_id"),
        table_name="edition_source_record",
    )
    op.drop_table("edition_source_record")
    for column in (
        "status",
        "right_source_record_id",
        "left_source_record_id",
        "confidence",
    ):
        op.drop_index(
            op.f(f"ix_edition_merge_proposal_{column}"),
            table_name="edition_merge_proposal",
        )
    op.drop_table("edition_merge_proposal")
    for column in (
        "wikidata_qid",
        "review_status",
        "publication_year",
        "openlibrary_edition_id",
        "oclc",
        "normalized_title",
        "isbn13",
        "isbn10",
        "google_books_id",
        "doi",
        "cluster_key",
        "canonical_work_id",
    ):
        op.drop_index(op.f(f"ix_edition_{column}"), table_name="edition")
    op.drop_table("edition")
