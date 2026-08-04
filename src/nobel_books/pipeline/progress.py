"""Durable per-source laureate discovery progress."""

from datetime import UTC, datetime

from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session, aliased

from nobel_books.models.database import DiscoveryQuery, Laureate

COMPLETION_QUERY = "__laureate_complete__"
COMPLETION_VARIANT = "laureate_complete"


def pending_laureates(
    session: Session,
    source: str,
    max_authors: int,
    *,
    nobel_api_id: str | None = None,
    refresh: bool = False,
) -> list[Laureate]:
    """Select the next incomplete cohort, or an explicitly requested refresh cohort."""

    query = select(Laureate).where(Laureate.is_organization.is_(False))
    if nobel_api_id is not None:
        query = query.where(Laureate.nobel_api_id == nobel_api_id).order_by(Laureate.id)
    elif not refresh:
        marker = aliased(DiscoveryQuery)
        query = (
            query.outerjoin(
                marker,
                (marker.laureate_id == Laureate.id)
                & (marker.source == source)
                & (marker.query_text == COMPLETION_QUERY),
            )
            .where(or_(marker.id.is_(None), marker.status != "succeeded"))
            .order_by(case((marker.id.is_(None), 0), else_=1), Laureate.id)
        )
    else:
        query = query.order_by(Laureate.id)
    return list(session.scalars(query.limit(max_authors)))


def mark_laureate_progress(
    session: Session,
    laureate: Laureate,
    source: str,
    status: str,
    *,
    result_count: int = 0,
) -> DiscoveryQuery:
    """Upsert the reserved completion marker for a source/laureate pair."""

    marker = session.scalar(
        select(DiscoveryQuery).where(
            DiscoveryQuery.laureate_id == laureate.id,
            DiscoveryQuery.source == source,
            DiscoveryQuery.query_text == COMPLETION_QUERY,
        )
    )
    if marker is None:
        marker = DiscoveryQuery(
            laureate_id=laureate.id,
            source=source,
            query_text=COMPLETION_QUERY,
        )
        session.add(marker)
    marker.variant_type = COMPLETION_VARIANT
    marker.status = status
    marker.result_count = result_count
    marker.executed_at = datetime.now(UTC)
    return marker
