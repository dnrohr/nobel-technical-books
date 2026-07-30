"""Nobel laureate ingestion service."""

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from nobel_books.adapters.nobel import FetchedPage, NobelApiAdapter, NobelLaureate, NobelPrize
from nobel_books.cache import RawResponseCache
from nobel_books.models.database import (
    Laureate,
    PipelineRun,
    PipelineStatus,
    PrizeAward,
    SourceFetch,
)

TARGET_CATEGORIES = {
    "physics": "physics",
    "chemistry": "chemistry",
    "physiology or medicine": "medicine",
    "medicine": "medicine",
}


@dataclass
class SyncSummary:
    laureates: int = 0
    organizations_skipped: int = 0
    pages: int = 0
    awards_by_category: Counter[str] = field(default_factory=Counter)
    awards_by_year: Counter[int] = field(default_factory=Counter)


def category_code(prize: NobelPrize) -> str | None:
    name = (prize.category.en or "").strip().casefold()
    return TARGET_CATEGORIES.get(name)


def _record_fetch(
    session: Session,
    run: PipelineRun,
    fetched: FetchedPage,
    cache: RawResponseCache,
) -> SourceFetch:
    cached = cache.store("nobel", fetched.content)
    request_key = hashlib.sha256(fetched.url.encode()).hexdigest()
    existing = session.scalar(
        select(SourceFetch).where(
            SourceFetch.source == "nobel",
            SourceFetch.request_key == request_key,
            SourceFetch.content_hash == cached.content_hash,
        )
    )
    if existing is not None:
        return existing
    record = SourceFetch(
        pipeline_run=run,
        source="nobel",
        request_url=fetched.url,
        request_key=request_key,
        fetched_at=datetime.now(UTC),
        status_code=fetched.status_code,
        content_hash=cached.content_hash,
        cache_path=cached.path.as_posix(),
    )
    session.add(record)
    session.flush()
    return record


def _upsert_laureate(
    session: Session,
    source: NobelLaureate,
    awards: list[tuple[NobelPrize, str]],
    source_fetch: SourceFetch,
) -> Laureate:
    now = datetime.now(UTC)
    laureate = session.scalar(select(Laureate).where(Laureate.nobel_api_id == source.id))
    if laureate is None:
        laureate = Laureate(
            nobel_api_id=source.id,
            display_name=source.display_name,
            created_at=now,
            updated_at=now,
        )
        session.add(laureate)

    laureate.display_name = source.display_name
    laureate.given_name = source.given_name.en if source.given_name else None
    laureate.family_name = source.family_name.en if source.family_name else None
    laureate.full_name_native = source.full_name.en if source.full_name else None
    laureate.gender = source.gender
    laureate.birth_date_raw = source.birth.date if source.birth else None
    laureate.death_date_raw = source.death.date if source.death else None
    laureate.is_organization = False
    laureate.updated_at = now
    session.flush()

    desired = {(category, int(prize.award_year)): prize for prize, category in awards}
    existing_awards = {
        (award.category, award.year): award
        for award in session.scalars(
            select(PrizeAward).where(PrizeAward.laureate_id == laureate.id)
        )
    }
    for key, prize in desired.items():
        award = existing_awards.get(key)
        if award is None:
            award = PrizeAward(laureate=laureate, category=key[0], year=key[1])
            session.add(award)
        award.motivation = prize.motivation.en if prize.motivation else None
        award.share = prize.prize_amount_share
        award.source_fetch_id = source_fetch.id

    stale_ids = [award.id for key, award in existing_awards.items() if key not in desired]
    if stale_ids:
        session.execute(delete(PrizeAward).where(PrizeAward.id.in_(stale_ids)))
    return laureate


def sync_laureates(
    session: Session,
    adapter: NobelApiAdapter,
    cache: RawResponseCache,
) -> SyncSummary:
    """Import all individual laureates with at least one target-category prize."""

    run = PipelineRun(
        profile="laureates-sync",
        status=PipelineStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()
    summary = SyncSummary()
    seen: set[str] = set()
    try:
        for fetched in adapter.pages():
            summary.pages += 1
            source_fetch = _record_fetch(session, run, fetched, cache)
            for source in fetched.page.laureates:
                if source.is_organization:
                    summary.organizations_skipped += 1
                    continue
                awards_by_key = {
                    (category, int(prize.award_year)): (prize, category)
                    for prize in source.nobel_prizes
                    if (category := category_code(prize)) is not None
                }
                awards = list(awards_by_key.values())
                if not awards:
                    continue
                _upsert_laureate(session, source, awards, source_fetch)
                seen.add(source.id)
                for prize, category in awards:
                    summary.awards_by_category[category] += 1
                    summary.awards_by_year[int(prize.award_year)] += 1
        summary.laureates = len(seen)
        run.status = PipelineStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)
        session.commit()
    except Exception as exc:
        session.rollback()
        run.status = PipelineStatus.FAILED
        run.finished_at = datetime.now(UTC)
        run.error_message = str(exc)
        session.add(run)
        session.commit()
        raise
    return summary
