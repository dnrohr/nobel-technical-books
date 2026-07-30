"""Initial SQLAlchemy database models."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative model base."""


class PipelineStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PipelineRun(Base):
    __tablename__ = "pipeline_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile: Mapped[str] = mapped_column(String(50), default="mvp")
    status: Mapped[PipelineStatus] = mapped_column(
        Enum(PipelineStatus, native_enum=False), default=PipelineStatus.RUNNING
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

    source_fetches: Mapped[list["SourceFetch"]] = relationship(back_populates="pipeline_run")


class SourceFetch(Base):
    __tablename__ = "source_fetch"
    __table_args__ = (
        UniqueConstraint("source", "request_key", "content_hash", name="uq_source_fetch_payload"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline_run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_run.id"))
    source: Mapped[str] = mapped_column(String(50), index=True)
    request_url: Mapped[str] = mapped_column(Text)
    request_key: Mapped[str] = mapped_column(String(64), index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status_code: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    cache_path: Mapped[str] = mapped_column(Text)

    pipeline_run: Mapped[PipelineRun | None] = relationship(back_populates="source_fetches")


class Laureate(Base):
    """An individual Nobel laureate in a target category."""

    __tablename__ = "laureate"

    id: Mapped[int] = mapped_column(primary_key=True)
    nobel_api_id: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(Text)
    given_name: Mapped[str | None] = mapped_column(Text)
    family_name: Mapped[str | None] = mapped_column(Text)
    full_name_native: Mapped[str | None] = mapped_column(Text)
    gender: Mapped[str | None] = mapped_column(String(30))
    birth_date_raw: Mapped[str | None] = mapped_column(String(30))
    death_date_raw: Mapped[str | None] = mapped_column(String(30))
    is_organization: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    prize_awards: Mapped[list["PrizeAward"]] = relationship(
        back_populates="laureate", cascade="all, delete-orphan"
    )


class PrizeAward(Base):
    """A target-category Nobel award associated with a laureate."""

    __tablename__ = "prize_award"
    __table_args__ = (
        UniqueConstraint("laureate_id", "category", "year", name="uq_laureate_prize"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    laureate_id: Mapped[int] = mapped_column(ForeignKey("laureate.id"), index=True)
    category: Mapped[str] = mapped_column(String(20), index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    motivation: Mapped[str | None] = mapped_column(Text)
    share: Mapped[str | None] = mapped_column(String(20))
    source_fetch_id: Mapped[int] = mapped_column(ForeignKey("source_fetch.id"))

    laureate: Mapped[Laureate] = relationship(back_populates="prize_awards")


class PersonNameVariant(Base):
    """An exact person-name spelling with a separate matching key."""

    __tablename__ = "person_name_variant"
    __table_args__ = (
        UniqueConstraint("laureate_id", "name", "source", name="uq_person_name_variant"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    laureate_id: Mapped[int] = mapped_column(ForeignKey("laureate.id"), index=True)
    name: Mapped[str] = mapped_column(Text)
    normalized_name: Mapped[str] = mapped_column(Text, index=True)
    language: Mapped[str | None] = mapped_column(String(20))
    script: Mapped[str | None] = mapped_column(String(30))
    source: Mapped[str] = mapped_column(String(50))
    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float)


class ExternalIdentity(Base):
    """An authority identifier connected to a laureate."""

    __tablename__ = "external_identity"
    __table_args__ = (UniqueConstraint("scheme", "value", name="uq_external_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    laureate_id: Mapped[int] = mapped_column(ForeignKey("laureate.id"), index=True)
    scheme: Mapped[str] = mapped_column(String(40), index=True)
    value: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    resolution_status: Mapped[str] = mapped_column(String(20), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    evidence_json: Mapped[dict[str, object]] = mapped_column(JSON)


class IdentityResolution(Base):
    """Latest deterministic Wikidata resolution result for a laureate."""

    __tablename__ = "identity_resolution"

    laureate_id: Mapped[int] = mapped_column(ForeignKey("laureate.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    candidate_qids: Mapped[list[str]] = mapped_column(JSON)
    source_fetch_id: Mapped[int] = mapped_column(ForeignKey("source_fetch.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SourceRecord(Base):
    """A parsed, source-native entity that has not been canonicalized."""

    __tablename__ = "source_record"
    __table_args__ = (
        UniqueConstraint(
            "source_fetch_id",
            "source",
            "source_entity_type",
            "source_entity_id",
            name="uq_source_record_fetch_entity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_fetch_id: Mapped[int] = mapped_column(ForeignKey("source_fetch.id"), index=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    source_entity_type: Mapped[str] = mapped_column(String(30), index=True)
    source_entity_id: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[dict[str, object]] = mapped_column(JSON)
    source_url: Mapped[str | None] = mapped_column(Text)


class Assertion(Base):
    """A field-level claim with direct source provenance."""

    __tablename__ = "assertion"
    __table_args__ = (
        UniqueConstraint(
            "source_record_id",
            "subject_type",
            "subject_id",
            "predicate",
            "value_hash",
            name="uq_assertion_value",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(30), index=True)
    subject_id: Mapped[int] = mapped_column(Integer, index=True)
    predicate: Mapped[str] = mapped_column(String(50), index=True)
    value_json: Mapped[object] = mapped_column(JSON)
    value_hash: Mapped[str] = mapped_column(String(64))
    source_record_id: Mapped[int] = mapped_column(ForeignKey("source_record.id"), index=True)
    reliability_class: Mapped[str] = mapped_column(String(5))
    confidence: Mapped[float] = mapped_column(Float)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    is_contradicted: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)


class SourceAuthorCandidate(Base):
    """A scored source-author identity candidate awaiting verification."""

    __tablename__ = "source_author_candidate"
    __table_args__ = (
        UniqueConstraint(
            "laureate_id",
            "source",
            "source_author_id",
            name="uq_source_author_candidate",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    laureate_id: Mapped[int] = mapped_column(ForeignKey("laureate.id"), index=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    source_author_id: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), index=True)
    evidence_json: Mapped[dict[str, object]] = mapped_column(JSON)
    source_fetch_id: Mapped[int | None] = mapped_column(ForeignKey("source_fetch.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DiscoveryQuery(Base):
    """A logged controlled query variant used for candidate recall."""

    __tablename__ = "discovery_query"
    __table_args__ = (
        UniqueConstraint("laureate_id", "source", "query_text", name="uq_discovery_query"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    laureate_id: Mapped[int] = mapped_column(ForeignKey("laureate.id"), index=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    query_text: Mapped[str] = mapped_column(Text)
    variant_type: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20))
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Edition(Base):
    """A reconciled publication manifestation built from source records."""

    __tablename__ = "edition"

    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    canonical_work_id: Mapped[int | None] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(Text)
    subtitle: Mapped[str | None] = mapped_column(Text)
    normalized_title: Mapped[str] = mapped_column(Text, index=True)
    language: Mapped[str | None] = mapped_column(String(30))
    publication_date_raw: Mapped[str | None] = mapped_column(Text)
    publication_year: Mapped[int | None] = mapped_column(Integer, index=True)
    edition_statement: Mapped[str | None] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(Text)
    publication_place: Mapped[str | None] = mapped_column(Text)
    format: Mapped[str | None] = mapped_column(String(40))
    page_count: Mapped[int | None] = mapped_column(Integer)
    isbn10: Mapped[str | None] = mapped_column(String(10), index=True)
    isbn13: Mapped[str | None] = mapped_column(String(13), index=True)
    doi: Mapped[str | None] = mapped_column(Text, index=True)
    oclc: Mapped[str | None] = mapped_column(Text, index=True)
    wikidata_qid: Mapped[str | None] = mapped_column(Text, index=True)
    openlibrary_edition_id: Mapped[str | None] = mapped_column(Text, index=True)
    google_books_id: Mapped[str | None] = mapped_column(Text, index=True)
    review_status: Mapped[str] = mapped_column(String(30), index=True)
    overall_confidence: Mapped[float] = mapped_column(Float)
    merge_method: Mapped[str] = mapped_column(String(40))
    identifier_issues: Mapped[list[dict[str, object]]] = mapped_column(JSON)


class EditionSourceRecord(Base):
    """Membership of a source-native record in a reconciled edition."""

    __tablename__ = "edition_source_record"

    source_record_id: Mapped[int] = mapped_column(ForeignKey("source_record.id"), primary_key=True)
    edition_id: Mapped[int] = mapped_column(ForeignKey("edition.id"), index=True)


class EditionMergeProposal(Base):
    """Deterministic evidence and conflicts for a candidate edition merge."""

    __tablename__ = "edition_merge_proposal"
    __table_args__ = (
        UniqueConstraint(
            "left_source_record_id",
            "right_source_record_id",
            name="uq_edition_merge_pair",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    left_source_record_id: Mapped[int] = mapped_column(ForeignKey("source_record.id"), index=True)
    right_source_record_id: Mapped[int] = mapped_column(ForeignKey("source_record.id"), index=True)
    confidence: Mapped[float] = mapped_column(Float, index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    evidence_json: Mapped[dict[str, object]] = mapped_column(JSON)
    conflicts_json: Mapped[list[str]] = mapped_column(JSON)
