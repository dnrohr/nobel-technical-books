"""Rule-based taxonomy and laureate-work relationship confidence."""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from nobel_books.models.database import (
    CanonicalWork,
    Contribution,
    Edition,
    EditionSourceRecord,
    ExternalIdentity,
    ManualOverride,
    SourceRecord,
    WorkSourceRecord,
)
from nobel_books.normalization.roles import normalize_role
from nobel_books.normalization.titles import normalize_title


class ClassificationRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    taxonomy: list[str]
    technical_indicators: list[str]
    textbook_indicators: list[str]
    reference_indicators: list[str]
    memoir_indicators: list[str]
    essay_indicators: list[str]
    fiction_indicators: list[str]
    audience: dict[str, list[str]] = Field(default_factory=dict)


@dataclass(frozen=True)
class ClassificationResult:
    work_type: str
    technicality_score: float
    audience: str
    confidence: float
    reason: str


@dataclass
class ClassificationSummary:
    classified: int = 0
    manual: int = 0
    low_confidence: int = 0
    contributions: int = 0
    contribution_reviews: int = 0


def load_rules(path: Path = Path("config/classification_rules.yaml")) -> ClassificationRules:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ClassificationRules.model_validate(loaded)


def _flatten(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _flatten(item)]
    if isinstance(value, list):
        return [text for item in value for text in _flatten(item)]
    return []


def _integer_values(value: object) -> list[int]:
    if isinstance(value, int):
        return [value]
    if isinstance(value, str) and value.isdigit():
        return [int(value)]
    if isinstance(value, dict):
        return [number for item in value.values() for number in _integer_values(item)]
    if isinstance(value, list):
        return [number for item in value for number in _integer_values(item)]
    return []


def _work_records(session: Session, work: CanonicalWork) -> list[SourceRecord]:
    direct = session.scalars(
        select(SourceRecord)
        .join(WorkSourceRecord, WorkSourceRecord.source_record_id == SourceRecord.id)
        .where(WorkSourceRecord.canonical_work_id == work.id)
    ).all()
    edition_records = session.scalars(
        select(SourceRecord)
        .join(
            EditionSourceRecord,
            EditionSourceRecord.source_record_id == SourceRecord.id,
        )
        .join(Edition, Edition.id == EditionSourceRecord.edition_id)
        .where(Edition.canonical_work_id == work.id)
    ).all()
    by_id = {record.id: record for record in (*direct, *edition_records)}
    return list(by_id.values())


def classify_metadata(
    title: str, metadata: list[str], sources: set[str], rules: ClassificationRules
) -> ClassificationResult:
    haystack = normalize_title(" ".join([title, *metadata]))

    def matches(indicators: list[str]) -> list[str]:
        return [indicator for indicator in indicators if normalize_title(indicator) in haystack]

    memoir = matches(rules.memoir_indicators)
    fiction = matches(rules.fiction_indicators)
    essays = matches(rules.essay_indicators)
    technical = matches(rules.technical_indicators)
    textbooks = matches(rules.textbook_indicators)
    references = matches(rules.reference_indicators)
    reasons: list[str] = []
    if memoir:
        work_type, score = "memoir", 0.1
        reasons.append(f"memoir indicators: {', '.join(memoir)}")
    elif fiction:
        work_type, score = "fiction", 0.05
        reasons.append(f"fiction indicators: {', '.join(fiction)}")
    elif essays:
        work_type, score = "essays", 0.2
        reasons.append(f"essay indicators: {', '.join(essays)}")
    elif references:
        work_type, score = "reference", min(1.0, 0.55 + 0.12 * len(technical))
        reasons.append(f"reference indicators: {', '.join(references)}")
    elif textbooks:
        work_type, score = "textbook", min(1.0, 0.6 + 0.12 * len(technical))
        reasons.append(f"textbook indicators: {', '.join(textbooks)}")
    elif technical:
        work_type, score = "technical_monograph", min(1.0, 0.45 + 0.12 * len(technical))
        reasons.append(f"technical indicators: {', '.join(technical)}")
    else:
        work_type, score = "unknown", 0.35
        reasons.append("no decisive deterministic taxonomy indicator")
    scholarly = sorted(sources & {"openalex", "crossref"})
    if scholarly and work_type not in {"memoir", "fiction", "essays"}:
        score = min(1.0, score + 0.15)
        reasons.append(f"scholarly source evidence: {', '.join(scholarly)}")
        if work_type == "unknown":
            work_type = "technical_monograph"
    audience = (
        "general" if work_type in {"memoir", "fiction", "essays", "popular_science"} else "unknown"
    )
    for level, indicators in rules.audience.items():
        hits = matches(indicators)
        if hits:
            audience = level
            reasons.append(f"{level} audience indicators: {', '.join(hits)}")
            break
    evidence_count = len(memoir or fiction or essays or references or textbooks or technical)
    confidence = min(0.98, 0.55 + 0.15 * evidence_count + 0.1 * len(scholarly))
    if work_type == "unknown":
        confidence = 0.45
    return ClassificationResult(
        work_type=work_type,
        technicality_score=round(score, 3),
        audience=audience,
        confidence=round(confidence, 3),
        reason="; ".join(reasons),
    )


def _manual_classification(session: Session, work: CanonicalWork) -> ManualOverride | None:
    return session.scalar(
        select(ManualOverride).where(
            ManualOverride.target_type == "canonical_work",
            ManualOverride.target_key == work.cluster_key,
            ManualOverride.action == "classify",
        )
    )


def classify_works(
    session: Session,
    rules: ClassificationRules,
) -> ClassificationSummary:
    summary = ClassificationSummary()
    works = session.scalars(select(CanonicalWork).order_by(CanonicalWork.id)).all()
    for work in works:
        records = _work_records(session, work)
        metadata = [value for record in records for value in _flatten(record.raw_json)]
        result = classify_metadata(
            work.preferred_title,
            metadata,
            {record.source for record in records},
            rules,
        )
        manual = _manual_classification(session, work)
        if manual is not None:
            payload = manual.payload_json
            work.work_type = str(payload.get("class", result.work_type))
            score = payload.get("score", result.technicality_score)
            work.technicality_score = (
                float(score) if isinstance(score, int | float) else result.technicality_score
            )
            work.audience_level = str(payload.get("audience", result.audience))
            work.classification_confidence = 1.0
            work.classification_method = "manual"
            work.classification_reason = f"Manual override: {manual.reason}"
            summary.manual += 1
        else:
            work.work_type = result.work_type
            work.technicality_score = result.technicality_score
            work.audience_level = result.audience
            work.classification_confidence = result.confidence
            work.classification_method = "deterministic_rules"
            work.classification_reason = result.reason
            if result.confidence < 0.75:
                work.review_status = "needs_review"
                summary.low_confidence += 1
        summary.classified += 1
    session.commit()
    return summary


@dataclass(frozen=True)
class RelationshipEvidence:
    laureate_id: int
    work_id: int
    role: str
    source: str
    source_record_id: int
    strength: float
    stable_identity: bool
    credited_name: str | None


def _identity_maps(session: Session) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = defaultdict(dict)
    for identity in session.scalars(
        select(ExternalIdentity).where(ExternalIdentity.resolution_status == "verified")
    ):
        result[identity.scheme][identity.value.rstrip("/").rsplit("/", 1)[-1]] = (
            identity.laureate_id
        )
    return result


def _record_work_id(session: Session, record: SourceRecord) -> int | None:
    direct = session.get(WorkSourceRecord, record.id)
    if direct is not None:
        return direct.canonical_work_id
    edition_link = session.get(EditionSourceRecord, record.id)
    if edition_link is None:
        return None
    edition = session.get(Edition, edition_link.edition_id)
    return edition.canonical_work_id if edition else None


def relationship_evidence(session: Session) -> list[RelationshipEvidence]:
    identities = _identity_maps(session)
    evidence: list[RelationshipEvidence] = []
    records = session.scalars(select(SourceRecord).order_by(SourceRecord.id)).all()
    for record in records:
        work_id = _record_work_id(session, record)
        if work_id is None:
            continue
        raw: dict[str, Any] = dict(record.raw_json)
        laureate_roles: list[tuple[int, str, bool, str | None]] = []
        if record.source == "wikidata":
            roles = [normalize_role(value) for value in _flatten(raw.get("role"))]
            for person in _flatten(raw.get("person")):
                qid = person.rstrip("/").rsplit("/", 1)[-1]
                laureate_id = identities["wikidata"].get(qid)
                if laureate_id:
                    for role in roles or ["unknown"]:
                        laureate_roles.append((laureate_id, role, True, None))
        elif record.source == "openlibrary":
            for author_id in _flatten(raw.get("author_id")):
                laureate_id = identities["openlibrary"].get(
                    author_id.rstrip("/").rsplit("/", 1)[-1]
                )
                if laureate_id:
                    laureate_roles.append((laureate_id, "author", True, None))
        else:
            for laureate_id in _integer_values(raw.get("candidate_for_laureate_id")):
                status = str(raw.get("relationship_status", "supported"))
                role = (
                    "author"
                    if status == "supported" and record.source != "wikipedia"
                    else "unknown"
                )
                names = _flatten(raw.get("authors"))
                laureate_roles.append(
                    (laureate_id, role, record.source == "openalex", names[0] if names else None)
                )
        for laureate_id, role, stable, credited_name in laureate_roles:
            strength = 0.55 if role in {"author", "coauthor", "editor", "coeditor"} else 0.15
            evidence.append(
                RelationshipEvidence(
                    laureate_id=laureate_id,
                    work_id=work_id,
                    role=role,
                    source=record.source,
                    source_record_id=record.id,
                    strength=strength,
                    stable_identity=stable,
                    credited_name=credited_name,
                )
            )
    return evidence


def score_relationships(session: Session) -> ClassificationSummary:
    grouped: dict[tuple[int, int, str], list[RelationshipEvidence]] = defaultdict(list)
    for item in relationship_evidence(session):
        grouped[(item.laureate_id, item.work_id, item.role)].append(item)
    summary = ClassificationSummary()
    for (laureate_id, work_id, role), items in grouped.items():
        sources = {item.source for item in items}
        confidence = max(item.strength for item in items)
        if len(sources) >= 2:
            confidence += 0.2
        if any(item.stable_identity for item in items):
            confidence += 0.1
        if role == "unknown":
            confidence -= 0.4
        if sources == {"wikipedia"}:
            confidence -= 0.25
        confidence = round(max(0.0, min(1.0, confidence)), 3)
        if confidence >= 0.9:
            status, included = "auto_accepted", True
        elif confidence >= 0.75:
            status, included = "provisional", True
        elif confidence >= 0.5:
            status, included = "needs_review", False
        else:
            status, included = "rejected", False
        contribution = session.scalar(
            select(Contribution).where(
                Contribution.laureate_id == laureate_id,
                Contribution.canonical_work_id == work_id,
                Contribution.edition_id.is_(None),
                Contribution.role == role,
            )
        )
        if contribution is None:
            contribution = Contribution(
                laureate_id=laureate_id,
                canonical_work_id=work_id,
                role=role,
            )
            session.add(contribution)
        contribution.credited_name = next(
            (item.credited_name for item in items if item.credited_name), None
        )
        contribution.relationship_confidence = confidence
        contribution.review_status = status
        contribution.is_default_included = included
        contribution.evidence_json = [
            {
                "source": item.source,
                "source_record_id": item.source_record_id,
                "strength": item.strength,
                "stable_identity": item.stable_identity,
            }
            for item in items
        ]
        summary.contributions += 1
        summary.contribution_reviews += int(not included)
    session.commit()
    return summary
