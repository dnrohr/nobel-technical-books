"""Initial SQLAlchemy database models."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
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
