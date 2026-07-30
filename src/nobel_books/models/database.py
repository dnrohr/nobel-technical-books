"""Initial SQLAlchemy database models."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
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
