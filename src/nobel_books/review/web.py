"""Local bibliography explorer and review interface."""

from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from nobel_books.classification.classifier import score_relationships
from nobel_books.models.database import (
    CanonicalWork,
    Contribution,
    Edition,
    EditionSourceRecord,
    ExternalIdentity,
    Laureate,
    PrizeAward,
    SourceRecord,
    WorkSourceRecord,
)
from nobel_books.review.workflow import record_review_decision, review_queue_items

PAGE = Path(__file__).with_name("explorer.html").read_text(encoding="utf-8")


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_key: str
    decision: str
    reason: str = Field(min_length=1)
    reviewer: str | None = None


def _prize_item(prize: PrizeAward) -> dict[str, object]:
    return {
        "category": prize.category,
        "year": prize.year,
        "subfield": prize.subfield,
        "award_summary": prize.motivation,
        "share": prize.share,
    }


def _laureate_item(session: Session, laureate: Laureate) -> dict[str, object]:
    prizes = session.scalars(
        select(PrizeAward)
        .where(PrizeAward.laureate_id == laureate.id)
        .order_by(PrizeAward.year, PrizeAward.category)
    ).all()
    contribution_counts: dict[str, int] = {
        str(row[0]): int(row[1])
        for row in session.execute(
            select(Contribution.review_status, func.count())
            .where(Contribution.laureate_id == laureate.id)
            .group_by(Contribution.review_status)
        )
    }
    return {
        "nobel_api_id": laureate.nobel_api_id,
        "name": laureate.display_name,
        "birth_date": laureate.birth_date_raw,
        "death_date": laureate.death_date_raw,
        "prizes": [_prize_item(prize) for prize in prizes],
        "work_count": sum(contribution_counts.values()),
        "verified_count": contribution_counts.get("verified", 0)
        + contribution_counts.get("auto_accepted", 0),
        "review_count": contribution_counts.get("needs_review", 0),
    }


def _work_item(
    session: Session,
    nobel_api_id: str,
    contribution: Contribution,
    work: CanonicalWork,
) -> dict[str, object]:
    editions = session.scalars(
        select(Edition)
        .where(Edition.canonical_work_id == work.id)
        .order_by(Edition.publication_year, Edition.title)
    ).all()
    source_rows = session.execute(
        select(SourceRecord)
        .join(WorkSourceRecord, WorkSourceRecord.source_record_id == SourceRecord.id)
        .where(WorkSourceRecord.canonical_work_id == work.id)
        .order_by(SourceRecord.source, SourceRecord.source_entity_id)
    ).scalars()
    sources = [
        {
            "source": record.source,
            "entity_type": record.source_entity_type,
            "entity_id": record.source_entity_id,
            "url": record.source_url,
        }
        for record in source_rows
    ]
    edition_items: list[dict[str, object]] = []
    for edition in editions:
        edition_sources = session.scalars(
            select(SourceRecord)
            .join(
                EditionSourceRecord,
                EditionSourceRecord.source_record_id == SourceRecord.id,
            )
            .where(EditionSourceRecord.edition_id == edition.id)
        ).all()
        edition_items.append(
            {
                "title": edition.title,
                "year": edition.publication_year,
                "language": edition.language,
                "publisher": edition.publisher,
                "format": edition.format,
                "isbn10": edition.isbn10,
                "isbn13": edition.isbn13,
                "doi": edition.doi,
                "oclc": edition.oclc,
                "confidence": edition.overall_confidence,
                "sources": [
                    {
                        "source": record.source,
                        "entity_id": record.source_entity_id,
                        "url": record.source_url,
                    }
                    for record in edition_sources
                ],
            }
        )
    return {
        "review_key": f"{nobel_api_id}::{work.cluster_key}::{contribution.role}",
        "title": work.preferred_title,
        "original_title": work.original_title,
        "year": work.first_publication_year,
        "role": contribution.role,
        "classification": work.work_type,
        "technicality": work.technicality_score,
        "audience": work.audience_level,
        "description": work.description,
        "series": work.series_title,
        "volume": work.volume_designation,
        "relationship_confidence": contribution.relationship_confidence,
        "overall_confidence": work.overall_confidence,
        "review_status": contribution.review_status,
        "classification_reason": work.classification_reason,
        "sources": sources,
        "editions": edition_items,
    }


def create_review_app(engine: Engine) -> FastAPI:
    """Create the local read-oriented explorer with optional review actions."""

    application = FastAPI(title="Nobel Books Explorer", docs_url=None, redoc_url=None)

    def database_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    @application.get("/", response_class=HTMLResponse)
    def index() -> str:
        return PAGE

    @application.get("/api/stats")
    def stats(
        session: Annotated[Session, Depends(database_session)],
    ) -> dict[str, object]:
        return {
            "laureates": session.scalar(select(func.count()).select_from(Laureate)) or 0,
            "works": session.scalar(select(func.count()).select_from(CanonicalWork)) or 0,
            "editions": session.scalar(select(func.count()).select_from(Edition)) or 0,
            "relationships": session.scalar(select(func.count()).select_from(Contribution)) or 0,
            "needs_review": session.scalar(
                select(func.count())
                .select_from(Contribution)
                .where(Contribution.review_status == "needs_review")
            )
            or 0,
            "zero_book_laureates": session.scalar(
                select(func.count())
                .select_from(Laureate)
                .where(
                    ~select(Contribution.id).where(Contribution.laureate_id == Laureate.id).exists()
                )
            )
            or 0,
        }

    @application.get("/api/filters")
    def filters(
        session: Annotated[Session, Depends(database_session)],
    ) -> dict[str, object]:
        return {
            "categories": list(
                session.scalars(
                    select(PrizeAward.category).distinct().order_by(PrizeAward.category)
                )
            ),
            "award_years": list(
                session.scalars(select(PrizeAward.year).distinct().order_by(PrizeAward.year.desc()))
            ),
            "subfields": list(
                session.scalars(
                    select(PrizeAward.subfield)
                    .where(PrizeAward.subfield.is_not(None))
                    .distinct()
                    .order_by(PrizeAward.subfield)
                )
            ),
        }

    @application.get("/api/laureates")
    def laureates(
        session: Annotated[Session, Depends(database_session)],
        q: str = "",
        category: str = "",
        award_year: int | None = None,
        subfield: str = "",
        book_status: str = "all",
        limit: Annotated[int, Query(ge=1, le=250)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, object]:
        query = select(Laureate).where(Laureate.is_organization.is_(False))
        if q.strip():
            pattern = f"%{q.strip()}%"
            query = query.where(
                or_(
                    Laureate.display_name.ilike(pattern),
                    Laureate.nobel_api_id.ilike(pattern),
                )
            )
        if category or award_year is not None or subfield:
            query = query.join(PrizeAward)
            if category:
                query = query.where(PrizeAward.category == category)
            if award_year is not None:
                query = query.where(PrizeAward.year == award_year)
            if subfield:
                query = query.where(PrizeAward.subfield == subfield)
        has_contribution = (
            select(Contribution.id).where(Contribution.laureate_id == Laureate.id).exists()
        )
        if book_status == "with_books":
            query = query.where(has_contribution)
        elif book_status == "zero_books":
            query = query.where(~has_contribution)
        query = query.distinct().order_by(Laureate.display_name)
        total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
        records = session.scalars(query.offset(offset).limit(limit)).all()
        return {
            "total": total,
            "offset": offset,
            "items": [_laureate_item(session, laureate) for laureate in records],
        }

    @application.get("/api/laureates/{nobel_api_id}")
    def laureate_detail(
        nobel_api_id: str,
        session: Annotated[Session, Depends(database_session)],
    ) -> dict[str, object]:
        laureate = session.scalar(select(Laureate).where(Laureate.nobel_api_id == nobel_api_id))
        if laureate is None:
            raise HTTPException(status_code=404, detail="Laureate not found")
        result = _laureate_item(session, laureate)
        result["identifiers"] = [
            {
                "scheme": identity.scheme,
                "value": identity.value,
                "url": identity.canonical_url,
                "status": identity.resolution_status,
            }
            for identity in session.scalars(
                select(ExternalIdentity)
                .where(ExternalIdentity.laureate_id == laureate.id)
                .order_by(ExternalIdentity.scheme)
            )
        ]
        contribution_rows = session.execute(
            select(Contribution, CanonicalWork)
            .join(CanonicalWork, CanonicalWork.id == Contribution.canonical_work_id)
            .where(Contribution.laureate_id == laureate.id)
            .order_by(CanonicalWork.first_publication_year, CanonicalWork.preferred_title)
        ).all()
        works = [
            _work_item(session, laureate.nobel_api_id, contribution, work)
            for contribution, work in contribution_rows
        ]
        result["works"] = works
        return result

    @application.get("/api/review")
    def review_queue(
        session: Annotated[Session, Depends(database_session)],
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> list[dict[str, object]]:
        return review_queue_items(session)[:limit]

    @application.post("/api/decision")
    def decide(
        decision: ReviewDecision,
        session: Annotated[Session, Depends(database_session)],
    ) -> dict[str, object]:
        try:
            override = record_review_decision(
                session,
                decision.review_key,
                decision.decision,
                decision.reason,
                decision.reviewer,
            )
            score_relationships(session)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "override_id": override.id,
            "target_type": override.target_type,
            "target_key": override.target_key,
            "action": override.action,
        }

    return application
