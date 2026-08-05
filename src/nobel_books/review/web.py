"""Local bibliography explorer and review interface."""

from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from nobel_books.classification.classifier import score_relationships
from nobel_books.models.database import (
    CanonicalWork,
    Contribution,
    Edition,
    EditionSourceRecord,
    ExternalIdentity,
    Laureate,
    PrizeAward,
    RetailRatingObservation,
    SourceRecord,
    WorkSourceRecord,
)
from nobel_books.review.ratings import amazon_search_url
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


def _valid_title_clause() -> ColumnElement[bool]:
    return and_(
        func.trim(CanonicalWork.preferred_title) != "",
        ~CanonicalWork.preferred_title.op("GLOB")("Q[0-9]*"),
    )


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
            .join(CanonicalWork, CanonicalWork.id == Contribution.canonical_work_id)
            .where(Contribution.laureate_id == laureate.id)
            .where(_valid_title_clause())
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
        rating = session.scalar(
            select(RetailRatingObservation)
            .where(RetailRatingObservation.edition_id == edition.id)
            .order_by(RetailRatingObservation.observed_at.desc())
        )
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
                "amazon_search_url": amazon_search_url(edition),
                "amazon_rating": (
                    {
                        "stars": rating.average_rating,
                        "review_count": rating.review_count,
                        "marketplace": rating.marketplace,
                        "asin": rating.product_id,
                        "observed_at": rating.observed_at.isoformat(),
                        "source_url": rating.source_url,
                        "match_confidence": rating.match_confidence,
                    }
                    if rating
                    else None
                ),
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
        "edition_count": len(editions),
        "source_count": len({str(source["source"]) for source in sources}),
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
            "works": session.scalar(
                select(func.count()).select_from(CanonicalWork).where(_valid_title_clause())
            )
            or 0,
            "editions": session.scalar(select(func.count()).select_from(Edition)) or 0,
            "relationships": session.scalar(
                select(func.count())
                .select_from(Contribution)
                .join(CanonicalWork, CanonicalWork.id == Contribution.canonical_work_id)
                .where(_valid_title_clause())
            )
            or 0,
            "needs_review": session.scalar(
                select(func.count())
                .select_from(Contribution)
                .join(CanonicalWork, CanonicalWork.id == Contribution.canonical_work_id)
                .where(Contribution.review_status == "needs_review")
                .where(_valid_title_clause())
            )
            or 0,
            "zero_book_laureates": session.scalar(
                select(func.count())
                .select_from(Laureate)
                .where(
                    ~select(Contribution.id)
                    .join(CanonicalWork, CanonicalWork.id == Contribution.canonical_work_id)
                    .where(Contribution.laureate_id == Laureate.id, _valid_title_clause())
                    .exists()
                )
            )
            or 0,
        }

    @application.get("/api/filters")
    def filters(
        session: Annotated[Session, Depends(database_session)],
    ) -> dict[str, object]:
        edition_counts = (
            select(
                CanonicalWork.id.label("work_id"),
                func.count(Edition.id).label("count"),
            )
            .outerjoin(Edition, Edition.canonical_work_id == CanonicalWork.id)
            .where(_valid_title_clause())
            .group_by(CanonicalWork.id)
            .subquery()
        )
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
            "publication_years": {
                "min": session.scalar(select(func.min(CanonicalWork.first_publication_year))),
                "max": session.scalar(select(func.max(CanonicalWork.first_publication_year))),
            },
            "edition_counts": {
                "max": session.scalar(select(func.max(edition_counts.c.count))) or 0,
            },
            "work_types": list(
                session.scalars(
                    select(CanonicalWork.work_type)
                    .where(_valid_title_clause())
                    .distinct()
                    .order_by(CanonicalWork.work_type)
                )
            ),
            "audiences": list(
                session.scalars(
                    select(CanonicalWork.audience_level)
                    .where(_valid_title_clause())
                    .distinct()
                    .order_by(CanonicalWork.audience_level)
                )
            ),
            "review_statuses": list(
                session.scalars(
                    select(Contribution.review_status)
                    .distinct()
                    .order_by(Contribution.review_status)
                )
            ),
            "roles": list(
                session.scalars(select(Contribution.role).distinct().order_by(Contribution.role))
            ),
            "sources": list(
                session.scalars(
                    select(SourceRecord.source).distinct().order_by(SourceRecord.source)
                )
            ),
        }

    @application.get("/api/laureates")
    def laureates(
        session: Annotated[Session, Depends(database_session)],
        q: str = "",
        category: str = "",
        award_year: int | None = None,
        award_year_from: int | None = None,
        award_year_to: int | None = None,
        subfield: str = "",
        book_status: str = "all",
        publication_year_from: int | None = None,
        publication_year_to: int | None = None,
        include_unknown_year: bool = True,
        edition_count: str = "any",
        min_editions: Annotated[int | None, Query(ge=0)] = None,
        max_editions: Annotated[int | None, Query(ge=0)] = None,
        review_status: str = "",
        role: str = "",
        work_type: str = "",
        audience: str = "",
        source: str = "",
        min_confidence: Annotated[float | None, Query(ge=0, le=1)] = None,
        min_technicality: Annotated[float | None, Query(ge=0, le=1)] = None,
        min_sources: Annotated[int | None, Query(ge=1)] = None,
        curated_only: bool = False,
        limit: Annotated[int, Query(ge=1, le=250)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, object]:
        query = select(Laureate).where(Laureate.is_organization.is_(False))
        edition_total = (
            select(func.count(Edition.id))
            .where(Edition.canonical_work_id == CanonicalWork.id)
            .correlate(CanonicalWork)
            .scalar_subquery()
        )
        source_total = (
            select(func.count(func.distinct(SourceRecord.source)))
            .join(WorkSourceRecord, WorkSourceRecord.source_record_id == SourceRecord.id)
            .where(WorkSourceRecord.canonical_work_id == CanonicalWork.id)
            .correlate(CanonicalWork)
            .scalar_subquery()
        )
        work_match = (
            select(Contribution.id)
            .join(CanonicalWork, CanonicalWork.id == Contribution.canonical_work_id)
            .where(Contribution.laureate_id == Laureate.id, _valid_title_clause())
        )
        if q.strip():
            pattern = f"%{q.strip()}%"
            edition_text_match = (
                select(Edition.id)
                .where(
                    Edition.canonical_work_id == CanonicalWork.id,
                    or_(
                        Edition.title.ilike(pattern),
                        Edition.isbn10.ilike(pattern),
                        Edition.isbn13.ilike(pattern),
                        Edition.oclc.ilike(pattern),
                    ),
                )
                .exists()
            )
            source_text_match = (
                select(SourceRecord.id)
                .join(WorkSourceRecord, WorkSourceRecord.source_record_id == SourceRecord.id)
                .where(
                    WorkSourceRecord.canonical_work_id == CanonicalWork.id,
                    SourceRecord.source_entity_id.ilike(pattern),
                )
                .exists()
            )
            title_match = work_match.where(
                or_(
                    CanonicalWork.preferred_title.ilike(pattern),
                    edition_text_match,
                    source_text_match,
                )
            ).exists()
            query = query.where(
                or_(
                    Laureate.display_name.ilike(pattern),
                    Laureate.nobel_api_id.ilike(pattern),
                    title_match,
                )
            )
        if (
            category
            or award_year is not None
            or award_year_from is not None
            or award_year_to is not None
            or subfield
        ):
            query = query.join(PrizeAward)
            if category:
                query = query.where(PrizeAward.category == category)
            if award_year is not None:
                query = query.where(PrizeAward.year == award_year)
            if award_year_from is not None:
                query = query.where(PrizeAward.year >= award_year_from)
            if award_year_to is not None:
                query = query.where(PrizeAward.year <= award_year_to)
            if subfield:
                query = query.where(PrizeAward.subfield == subfield)
        if publication_year_from is not None:
            condition = CanonicalWork.first_publication_year >= publication_year_from
            work_match = work_match.where(
                or_(condition, CanonicalWork.first_publication_year.is_(None))
                if include_unknown_year
                else condition
            )
        if publication_year_to is not None:
            condition = CanonicalWork.first_publication_year <= publication_year_to
            work_match = work_match.where(
                or_(condition, CanonicalWork.first_publication_year.is_(None))
                if include_unknown_year
                else condition
            )
        if edition_count == "none":
            work_match = work_match.where(edition_total == 0)
        elif edition_count == "one":
            work_match = work_match.where(edition_total == 1)
        elif edition_count == "multiple":
            work_match = work_match.where(edition_total >= 2)
        if min_editions is not None:
            work_match = work_match.where(edition_total >= min_editions)
        if max_editions is not None:
            work_match = work_match.where(edition_total <= max_editions)
        if review_status:
            work_match = work_match.where(Contribution.review_status == review_status)
        if role:
            work_match = work_match.where(Contribution.role == role)
        if work_type:
            work_match = work_match.where(CanonicalWork.work_type == work_type)
        if audience:
            work_match = work_match.where(CanonicalWork.audience_level == audience)
        if min_confidence is not None:
            work_match = work_match.where(Contribution.relationship_confidence >= min_confidence)
        if min_technicality is not None:
            work_match = work_match.where(CanonicalWork.technicality_score >= min_technicality)
        if min_sources is not None:
            work_match = work_match.where(source_total >= min_sources)
        if curated_only:
            work_match = work_match.where(
                or_(
                    Contribution.is_default_included.is_(True),
                    Contribution.review_status.in_(("verified", "auto_accepted")),
                )
            )
        if source:
            has_source = (
                select(SourceRecord.id)
                .join(WorkSourceRecord, WorkSourceRecord.source_record_id == SourceRecord.id)
                .where(
                    WorkSourceRecord.canonical_work_id == CanonicalWork.id,
                    SourceRecord.source == source,
                )
                .exists()
            )
            work_match = work_match.where(has_source)
        has_contribution = work_match.exists()
        work_filters_active = any(
            (
                publication_year_from is not None,
                publication_year_to is not None,
                edition_count != "any",
                min_editions is not None,
                max_editions is not None,
                bool(review_status),
                bool(role),
                bool(work_type),
                bool(audience),
                bool(source),
                min_confidence is not None,
                min_technicality is not None,
                min_sources is not None,
                curated_only,
            )
        )
        if book_status == "with_books":
            query = query.where(has_contribution)
        elif book_status == "zero_books":
            query = query.where(~has_contribution)
        elif work_filters_active:
            query = query.where(has_contribution)
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
        work_limit: Annotated[int, Query(ge=1, le=200)] = 100,
        work_offset: Annotated[int, Query(ge=0)] = 0,
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
        contribution_query = (
            select(Contribution, CanonicalWork)
            .join(CanonicalWork, CanonicalWork.id == Contribution.canonical_work_id)
            .where(Contribution.laureate_id == laureate.id, _valid_title_clause())
            .order_by(CanonicalWork.first_publication_year, CanonicalWork.preferred_title)
        )
        work_total = (
            session.scalar(select(func.count()).select_from(contribution_query.subquery())) or 0
        )
        contribution_rows = session.execute(
            contribution_query.offset(work_offset).limit(work_limit)
        ).all()
        works = [
            _work_item(session, laureate.nobel_api_id, contribution, work)
            for contribution, work in contribution_rows
        ]
        result["works"] = works
        result["work_total"] = work_total
        result["work_offset"] = work_offset
        result["work_limit"] = work_limit
        result["works_truncated"] = work_offset + len(works) < work_total
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
