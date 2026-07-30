"""Exact Nobel-ID-to-Wikidata identity resolution."""

import csv
import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from nobel_books.adapters.wikidata import (
    IDENTIFIER_PROPERTIES,
    BindingValue,
    FetchedBindings,
    WikidataIdentityAdapter,
)
from nobel_books.cache import RawResponseCache
from nobel_books.models.database import (
    ExternalIdentity,
    IdentityResolution,
    Laureate,
    PersonNameVariant,
    PipelineRun,
    PipelineStatus,
    SourceFetch,
)
from nobel_books.normalization.names import normalize_name


@dataclass
class IdentitySummary:
    verified: int = 0
    unresolved: int = 0
    ambiguous: int = 0
    batches: int = 0


def qid_from_uri(uri: str) -> str:
    return uri.rstrip("/").rsplit("/", 1)[-1]


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


def _upsert_identity(
    session: Session,
    laureate: Laureate,
    scheme: str,
    value: str,
    url: str | None,
    evidence: dict[str, object],
) -> None:
    identity = session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.scheme == scheme, ExternalIdentity.value == value
        )
    )
    if identity is None:
        identity = ExternalIdentity(scheme=scheme, value=value)
        session.add(identity)
    identity.laureate_id = laureate.id
    identity.canonical_url = url
    identity.resolution_status = "verified"
    identity.confidence = 1.0
    identity.evidence_json = evidence


def _upsert_name(
    session: Session,
    laureate: Laureate,
    name: str,
    *,
    language: str | None,
    preferred: bool,
) -> None:
    variant = session.scalar(
        select(PersonNameVariant).where(
            PersonNameVariant.laureate_id == laureate.id,
            PersonNameVariant.name == name,
            PersonNameVariant.source == "wikidata",
        )
    )
    if variant is None:
        variant = PersonNameVariant(laureate_id=laureate.id, name=name, source="wikidata")
        session.add(variant)
    variant.normalized_name = normalize_name(name)
    variant.language = language
    variant.script = None
    variant.is_preferred = preferred
    variant.confidence = 1.0


def _values(rows: list[dict[str, BindingValue]], key: str) -> set[str]:
    return {row[key].value for row in rows if key in row}


def _resolve_one(
    session: Session,
    laureate: Laureate,
    rows: list[dict[str, BindingValue]],
    fetch: SourceFetch,
) -> str:
    qids = sorted({qid_from_uri(value) for value in _values(rows, "person")})
    status = "verified" if len(qids) == 1 else "unresolved" if not qids else "ambiguous"
    resolution = session.get(IdentityResolution, laureate.id)
    if resolution is None:
        resolution = IdentityResolution(laureate_id=laureate.id)
        session.add(resolution)
    resolution.status = status
    resolution.confidence = 1.0 if status == "verified" else 0.0
    resolution.candidate_qids = qids
    resolution.source_fetch_id = fetch.id
    resolution.updated_at = datetime.now(UTC)
    if status != "verified":
        return status

    qid = qids[0]
    qid_rows = [row for row in rows if qid_from_uri(row["person"].value) == qid]
    evidence: dict[str, object] = {
        "method": "exact_p8024",
        "nobel_api_id": laureate.nobel_api_id,
    }
    _upsert_identity(
        session,
        laureate,
        "wikidata",
        qid,
        f"https://www.wikidata.org/wiki/{qid}",
        evidence,
    )
    urls = {
        "orcid": "https://orcid.org/{value}",
        "viaf": "https://viaf.org/viaf/{value}",
        "isni": "https://isni.org/isni/{value}",
        "gnd": "https://d-nb.info/gnd/{value}",
        "lcnaf": "https://id.loc.gov/authorities/names/{value}",
        "openlibrary": "https://openlibrary.org/authors/{value}",
    }
    for scheme in IDENTIFIER_PROPERTIES:
        for value in _values(qid_rows, scheme):
            _upsert_identity(
                session,
                laureate,
                scheme,
                value,
                urls[scheme].format(value=value),
                {"method": "wikidata_statement", "wikidata_qid": qid},
            )
    for name in _values(qid_rows, "personLabel"):
        _upsert_name(session, laureate, name, language="en", preferred=True)
    for name in _values(qid_rows, "altLabel"):
        _upsert_name(session, laureate, name, language="en", preferred=False)
    return status


def resolve_identities(
    session: Session,
    adapter: WikidataIdentityAdapter,
    cache: RawResponseCache,
) -> IdentitySummary:
    laureates = session.scalars(select(Laureate).order_by(Laureate.id)).all()
    by_nobel_id = {laureate.nobel_api_id: laureate for laureate in laureates}
    run = PipelineRun(
        profile="identities-resolve",
        status=PipelineStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()
    summary = IdentitySummary()
    try:
        for fetched in adapter.batches(list(by_nobel_id)):
            summary.batches += 1
            source_fetch = _record_fetch(session, run, fetched, cache)
            grouped: dict[str, list[dict[str, BindingValue]]] = defaultdict(list)
            for row in fetched.bindings:
                if "nobelId" in row:
                    grouped[row["nobelId"].value].append(row)
            for nobel_id in fetched.nobel_ids:
                status = _resolve_one(
                    session, by_nobel_id[nobel_id], grouped[nobel_id], source_fetch
                )
                setattr(summary, status, getattr(summary, status) + 1)
        run.status = PipelineStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)
        session.commit()
    except Exception as exc:
        session.rollback()
        failed = PipelineRun(
            profile="identities-resolve",
            status=PipelineStatus.FAILED,
            started_at=run.started_at,
            finished_at=datetime.now(UTC),
            error_message=str(exc),
        )
        session.add(failed)
        session.commit()
        raise
    return summary


def export_identity_review(session: Session, path: Path) -> int:
    """Export unresolved and ambiguous laureates for deterministic review."""

    rows = session.execute(
        select(Laureate, IdentityResolution)
        .join(IdentityResolution, IdentityResolution.laureate_id == Laureate.id)
        .where(IdentityResolution.status.in_(("unresolved", "ambiguous")))
        .order_by(Laureate.display_name)
    ).all()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["nobel_api_id", "display_name", "status", "candidate_qids"])
        for laureate, resolution in rows:
            writer.writerow(
                [
                    laureate.nobel_api_id,
                    laureate.display_name,
                    resolution.status,
                    "|".join(resolution.candidate_qids),
                ]
            )
    return len(rows)
