"""Source-native candidate discovery and assertion persistence."""

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from nobel_books.adapters.wikidata import (
    BindingValue,
    FetchedBindings,
    WikidataBookAdapter,
)
from nobel_books.cache import RawResponseCache
from nobel_books.models.database import (
    Assertion,
    ExternalIdentity,
    PipelineRun,
    PipelineStatus,
    SourceFetch,
    SourceRecord,
)
from nobel_books.pipeline.identities import qid_from_uri


@dataclass
class DiscoverySummary:
    batches: int = 0
    records: int = 0
    works: int = 0
    editions: int = 0
    assertions: int = 0


_WIKIDATA_ENTITY_ID = re.compile(r"^Q\d+$", re.IGNORECASE)


def is_valid_human_title(value: str | None) -> bool:
    """Return whether a source value is a usable human-readable book title."""

    title = " ".join((value or "").split())
    return bool(title) and not _WIKIDATA_ENTITY_ID.fullmatch(title)


def _record_fetch(
    session: Session,
    run: PipelineRun,
    fetched: FetchedBindings,
    cache: RawResponseCache,
) -> SourceFetch:
    cached = cache.store("wikidata", fetched.content)
    request_key = hashlib.sha256(fetched.url.encode()).hexdigest()
    existing = session.scalar(
        select(SourceFetch).where(
            SourceFetch.source == "wikidata",
            SourceFetch.request_key == request_key,
            SourceFetch.content_hash == cached.content_hash,
        )
    )
    if existing is not None:
        return existing
    record = SourceFetch(
        pipeline_run=run,
        source="wikidata",
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


def _group_values(rows: list[dict[str, BindingValue]], key: str) -> list[dict[str, str]]:
    unique = {(row[key].value, row[key].language) for row in rows if key in row}
    return [
        {"value": value, **({"language": language} if language else {})}
        for value, language in sorted(unique)
    ]


def _upsert_assertion(
    session: Session,
    record: SourceRecord,
    predicate: str,
    value: object,
    *,
    reliability_class: str = "B",
    confidence: float = 0.9,
) -> bool:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    value_hash = hashlib.sha256(encoded.encode()).hexdigest()
    existing = session.scalar(
        select(Assertion).where(
            Assertion.source_record_id == record.id,
            Assertion.subject_type == record.source_entity_type,
            Assertion.subject_id == record.id,
            Assertion.predicate == predicate,
            Assertion.value_hash == value_hash,
        )
    )
    if existing is not None:
        return False
    session.add(
        Assertion(
            subject_type=record.source_entity_type,
            subject_id=record.id,
            predicate=predicate,
            value_json=value,
            value_hash=value_hash,
            source_record_id=record.id,
            reliability_class=reliability_class,
            confidence=confidence,
            is_selected=False,
            is_contradicted=False,
        )
    )
    return True


def _parse_item(
    session: Session,
    rows: list[dict[str, BindingValue]],
    source_fetch: SourceFetch,
) -> tuple[SourceRecord, int]:
    item_qid = qid_from_uri(rows[0]["item"].value)
    raw: dict[str, list[dict[str, str]]] = {}
    field_map = {
        "instance": "instance",
        "instance_label": "instanceLabel",
        "role": "role",
        "person": "person",
        "publication_date": "publicationDate",
        "isbn13": "isbn13",
        "isbn10": "isbn10",
        "oclc": "oclc",
        "edition_of": "editionOf",
        "edition_of_label": "editionOfLabel",
    }
    title_values = _group_values(rows, "explicitItemLabel") or _group_values(rows, "itemLabel")
    title_values = [value for value in title_values if is_valid_human_title(value.get("value"))]
    if title_values:
        raw["title"] = title_values
    for predicate, binding_key in field_map.items():
        values = _group_values(rows, binding_key)
        if values:
            raw[predicate] = values
    entity_type = "edition" if "edition_of" in raw else "work"
    record = session.scalar(
        select(SourceRecord).where(
            SourceRecord.source_fetch_id == source_fetch.id,
            SourceRecord.source == "wikidata",
            SourceRecord.source_entity_type == entity_type,
            SourceRecord.source_entity_id == item_qid,
        )
    )
    if record is None:
        record_json: dict[str, object] = {key: values for key, values in raw.items()}
        record = SourceRecord(
            source_fetch_id=source_fetch.id,
            source="wikidata",
            source_entity_type=entity_type,
            source_entity_id=item_qid,
            raw_json=record_json,
            source_url=f"https://www.wikidata.org/wiki/{item_qid}",
        )
        session.add(record)
        session.flush()
    record_json = {key: values for key, values in raw.items()}
    record.raw_json = record_json
    record.source_url = f"https://www.wikidata.org/wiki/{item_qid}"
    assertion_count = sum(
        _upsert_assertion(session, record, predicate, value)
        for predicate, values in raw.items()
        for value in values
    )
    return record, assertion_count


def discover_wikidata_candidates(
    session: Session,
    adapter: WikidataBookAdapter,
    cache: RawResponseCache,
) -> DiscoverySummary:
    qids = session.scalars(
        select(ExternalIdentity.value)
        .where(
            ExternalIdentity.scheme == "wikidata",
            ExternalIdentity.resolution_status == "verified",
        )
        .order_by(ExternalIdentity.value)
    ).all()
    run = PipelineRun(
        profile="discover-wikidata",
        status=PipelineStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()
    summary = DiscoverySummary()
    try:
        for fetched in adapter.batches(qids):
            summary.batches += 1
            source_fetch = _record_fetch(session, run, fetched, cache)
            grouped: dict[str, list[dict[str, BindingValue]]] = defaultdict(list)
            for row in fetched.bindings:
                if "item" in row:
                    grouped[qid_from_uri(row["item"].value)].append(row)
            for rows in grouped.values():
                record, assertion_count = _parse_item(session, rows, source_fetch)
                summary.records += 1
                summary.assertions += assertion_count
                if record.source_entity_type == "edition":
                    summary.editions += 1
                else:
                    summary.works += 1
        run.status = PipelineStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)
        session.commit()
    except Exception as exc:
        session.rollback()
        session.add(
            PipelineRun(
                profile="discover-wikidata",
                status=PipelineStatus.FAILED,
                started_at=run.started_at,
                finished_at=datetime.now(UTC),
                error_message=str(exc),
            )
        )
        session.commit()
        raise
    return summary
