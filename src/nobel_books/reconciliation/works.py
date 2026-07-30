"""Canonical work clustering with durable manual overrides."""

import csv
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field
from rapidfuzz.fuzz import ratio
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from nobel_books.models.database import (
    CanonicalWork,
    Edition,
    EditionSourceRecord,
    ManualOverride,
    SourceRecord,
    WorkMergeProposal,
    WorkRelation,
    WorkSourceRecord,
)
from nobel_books.normalization.titles import normalize_title
from nobel_books.reconciliation.editions import UnionFind, _strings


class OverrideInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: str
    target_key: str
    action: str
    payload: dict[str, object] = Field(default_factory=dict)
    reason: str
    reviewer: str | None = None


class OverrideFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overrides: list[OverrideInput] = Field(default_factory=list)


@dataclass
class WorkGroup:
    tokens: set[str] = field(default_factory=set)
    editions: list[Edition] = field(default_factory=list)
    source_records: list[SourceRecord] = field(default_factory=list)


@dataclass
class WorkSummary:
    works: int = 0
    editions_linked: int = 0
    source_works_linked: int = 0
    series_works: int = 0
    review_items: int = 0
    overrides_applied: int = 0


def _source_token(source: str, source_id: str) -> str:
    return f"{source}:{source_id}"


def _qid(value: str) -> str:
    return value.rstrip("/").rsplit("/", 1)[-1]


def _edition_explicit_tokens(
    records: list[SourceRecord],
) -> set[str]:
    tokens: set[str] = set()
    for record in records:
        raw: dict[str, Any] = dict(record.raw_json)
        if record.source == "openlibrary":
            for value in _strings(raw.get("work_id")):
                tokens.add(_source_token("openlibrary", value.strip("/").rsplit("/", 1)[-1]))
        if record.source == "wikidata":
            for value in _strings(raw.get("edition_of")):
                tokens.add(_source_token("wikidata", _qid(value)))
    return tokens


def load_overrides(session: Session, path: Path) -> int:
    if not path.exists():
        return 0
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    document = OverrideFile.model_validate(loaded)
    count = 0
    for item in document.overrides:
        override = session.scalar(
            select(ManualOverride).where(
                ManualOverride.target_type == item.target_type,
                ManualOverride.target_key == item.target_key,
                ManualOverride.action == item.action,
            )
        )
        if override is None:
            override = ManualOverride(
                target_type=item.target_type,
                target_key=item.target_key,
                action=item.action,
                created_at=datetime.now(UTC),
            )
            session.add(override)
        override.payload_json = item.payload
        override.reason = item.reason
        override.reviewer = item.reviewer
        count += 1
    session.flush()
    return count


def _raw_series(records: list[SourceRecord]) -> tuple[str | None, str | None]:
    for record in records:
        raw: dict[str, Any] = dict(record.raw_json)
        series = next(
            (value for key in ("series_title", "series") for value in _strings(raw.get(key))),
            None,
        )
        volume = next(
            (
                value
                for key in ("volume_designation", "volume", "volumeInfo")
                for value in _strings(raw.get(key))
            ),
            None,
        )
        if series:
            return series, volume
    return None, None


def _upsert_work(
    session: Session,
    group: WorkGroup,
    cluster_key: str,
    *,
    work_type: str = "unknown",
    forced_title: str | None = None,
) -> CanonicalWork:
    candidates: list[tuple[int, str, str, int | None, str | None]] = []
    source_priority = {"wikidata": 0, "openlibrary": 1, "google_books": 2}
    for record in group.source_records:
        title = next(
            (
                value
                for key in ("title", "itemLabel")
                for value in _strings(dict(record.raw_json).get(key))
            ),
            None,
        )
        if title:
            candidates.append(
                (
                    source_priority.get(record.source, 9),
                    record.source_entity_id or "",
                    title,
                    None,
                    None,
                )
            )
    for edition in group.editions:
        candidates.append(
            (
                5,
                edition.cluster_key,
                edition.title,
                edition.publication_year,
                edition.language,
            )
        )
    candidates.sort()
    title = forced_title or (candidates[0][2] if candidates else "Untitled work")
    years = [item[3] for item in candidates if item[3] is not None]
    languages = [item[4] for item in candidates if item[4]]
    now = datetime.now(UTC)
    work = session.scalar(select(CanonicalWork).where(CanonicalWork.cluster_key == cluster_key))
    if work is None:
        work = CanonicalWork(
            cluster_key=cluster_key,
            preferred_title=title,
            normalized_title=normalize_title(title),
            work_type=work_type,
            review_status="unreviewed",
            overall_confidence=0.8,
            created_at=now,
            updated_at=now,
        )
        session.add(work)
        session.flush()
    work.preferred_title = title
    work.normalized_title = normalize_title(title)
    work.first_publication_year = min(years) if years else None
    work.original_language = languages[0] if languages else None
    work.work_type = work_type
    work.review_status = "auto_accepted" if group.editions else "unreviewed"
    work.overall_confidence = 0.95 if group.editions else 0.75
    work.updated_at = now
    return work


def cluster_works(
    session: Session,
    *,
    override_path: Path = Path("data/manual/work_overrides.yaml"),
    review_path: Path = Path("data/exports/work_review_queue.csv"),
) -> WorkSummary:
    loaded_count = load_overrides(session, override_path)
    source_works = session.scalars(
        select(SourceRecord)
        .where(SourceRecord.source_entity_type == "work")
        .order_by(SourceRecord.source, SourceRecord.source_entity_id)
    ).all()
    editions = session.scalars(select(Edition).order_by(Edition.cluster_key)).all()
    edition_records: dict[int, list[SourceRecord]] = {}
    for edition in editions:
        edition_records[edition.id] = list(
            session.scalars(
                select(SourceRecord)
                .join(
                    EditionSourceRecord,
                    EditionSourceRecord.source_record_id == SourceRecord.id,
                )
                .where(EditionSourceRecord.edition_id == edition.id)
            ).all()
        )

    tokens = {
        _source_token(record.source, record.source_entity_id)
        for record in source_works
        if record.source_entity_id
    }
    edition_tokens: dict[int, set[str]] = {}
    split_keys = {
        override.target_key
        for override in session.scalars(
            select(ManualOverride).where(
                ManualOverride.target_type == "edition",
                ManualOverride.action == "split",
            )
        )
    }
    for edition in editions:
        stable_key = f"edition:{edition.cluster_key}"
        explicit = _edition_explicit_tokens(edition_records[edition.id])
        if stable_key in split_keys or not explicit:
            explicit = {stable_key}
        edition_tokens[edition.id] = explicit
        tokens.update(explicit)
    union = UnionFind(sorted(tokens))
    for explicit in edition_tokens.values():
        ordered = sorted(explicit)
        for token in ordered[1:]:
            union.union(ordered[0], token)
    applied = loaded_count
    for override in session.scalars(
        select(ManualOverride).where(
            ManualOverride.target_type == "work_cluster",
            ManualOverride.action == "merge",
        )
    ):
        other = override.payload_json.get("with")
        if isinstance(other, str) and override.target_key in tokens and other in tokens:
            union.union(override.target_key, other)
            applied += int(override not in session.new)

    groups: dict[str, WorkGroup] = {}
    for token in sorted(tokens):
        root = union.find(token)
        groups.setdefault(root, WorkGroup()).tokens.add(token)
    for record in source_works:
        if record.source_entity_id:
            token = _source_token(record.source, record.source_entity_id)
            groups[union.find(token)].source_records.append(record)
    for edition in editions:
        root = union.find(sorted(edition_tokens[edition.id])[0])
        groups[root].editions.append(edition)
        groups[root].source_records.extend(edition_records[edition.id])

    session.execute(delete(WorkMergeProposal))
    session.execute(delete(WorkRelation))
    created: list[tuple[CanonicalWork, WorkGroup]] = []
    for group in sorted(groups.values(), key=lambda item: sorted(item.tokens)):
        key = hashlib.sha256("\n".join(sorted(group.tokens)).encode()).hexdigest()
        work = _upsert_work(session, group, key)
        created.append((work, group))
        for edition in group.editions:
            edition.canonical_work_id = work.id
        for record in group.source_records:
            if record.source_entity_type != "work":
                continue
            link = session.get(WorkSourceRecord, record.id)
            if link is None:
                link = WorkSourceRecord(source_record_id=record.id)
                session.add(link)
            link.canonical_work_id = work.id
    session.flush()

    series_count = 0
    for work, group in list(created):
        series, volume = _raw_series(group.source_records)
        if not series or normalize_title(series) == work.normalized_title:
            continue
        series_key = hashlib.sha256(f"series:{normalize_title(series)}".encode()).hexdigest()
        series_group = WorkGroup(tokens={f"series:{normalize_title(series)}"})
        series_work = _upsert_work(
            session, series_group, series_key, work_type="series", forced_title=series
        )
        work.series_title = series
        work.volume_designation = volume
        session.add(
            WorkRelation(
                parent_work_id=series_work.id,
                child_work_id=work.id,
                relation_type="volume",
                evidence_json={"series_title": series, "volume_designation": volume},
            )
        )
        series_count += 1

    review_items = 0
    works = [item[0] for item in created]
    for index, left in enumerate(works):
        for right in works[index + 1 :]:
            similarity = ratio(left.normalized_title, right.normalized_title) / 100
            if similarity < 0.82:
                continue
            session.add(
                WorkMergeProposal(
                    left_work_id=min(left.id, right.id),
                    right_work_id=max(left.id, right.id),
                    confidence=similarity,
                    status="merge_review",
                    evidence_json={"title_similarity": similarity},
                )
            )
            review_items += 1
    for work, group in created:
        titles = {normalize_title(edition.title) for edition in group.editions}
        if (
            len(titles) > 1
            and min(
                ratio(left, right) / 100 for left in titles for right in titles if left != right
            )
            < 0.5
        ):
            session.add(
                WorkMergeProposal(
                    left_work_id=work.id,
                    right_work_id=work.id,
                    confidence=0.5,
                    status="split_review",
                    evidence_json={"edition_titles": sorted(titles)},
                )
            )
            review_items += 1
    session.commit()
    export_work_review(session, review_path)
    return WorkSummary(
        works=len(created) + series_count,
        editions_linked=len(editions),
        source_works_linked=len(source_works),
        series_works=series_count,
        review_items=review_items,
        overrides_applied=applied,
    )


def export_work_review(session: Session, path: Path) -> int:
    proposals = session.scalars(
        select(WorkMergeProposal).order_by(
            WorkMergeProposal.status,
            WorkMergeProposal.confidence.desc(),
            WorkMergeProposal.id,
        )
    ).all()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                "status",
                "left_work_id",
                "left_title",
                "right_work_id",
                "right_title",
                "confidence",
                "reviewer_decision",
                "reviewer_reason",
            ]
        )
        for proposal in proposals:
            left = session.get(CanonicalWork, proposal.left_work_id)
            right = session.get(CanonicalWork, proposal.right_work_id)
            writer.writerow(
                [
                    proposal.status,
                    proposal.left_work_id,
                    left.preferred_title if left else "",
                    proposal.right_work_id,
                    right.preferred_title if right else "",
                    f"{proposal.confidence:.3f}",
                    "",
                    "",
                ]
            )
    return len(proposals)
