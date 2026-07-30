"""Deterministic audit snapshots and comparisons."""

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from nobel_books.models.database import (
    CanonicalWork,
    Contribution,
    DiscoveryQuery,
    ExternalIdentity,
    Laureate,
    ManualOverride,
    SourceRecord,
)


def _contribution_key(laureate: Laureate, work: CanonicalWork, role: str) -> str:
    return f"{laureate.nobel_api_id}::{work.cluster_key}::{role}"


def dataset_snapshot(session: Session) -> dict[str, object]:
    """Build the stable portion of an accepted dataset for later comparison."""

    identities: dict[int, list[str]] = defaultdict(list)
    for identity in session.scalars(select(ExternalIdentity)).all():
        identities[identity.laureate_id].append(f"{identity.scheme}:{identity.value}")

    works: dict[str, dict[str, object]] = {}
    rows = session.execute(
        select(Contribution, Laureate, CanonicalWork)
        .join(Laureate, Laureate.id == Contribution.laureate_id)
        .join(CanonicalWork, CanonicalWork.id == Contribution.canonical_work_id)
    ).all()
    for contribution, laureate, work in rows:
        key = _contribution_key(laureate, work, contribution.role)
        works[key] = {
            "nobel_api_id": laureate.nobel_api_id,
            "cluster_key": work.cluster_key,
            "title": work.preferred_title,
            "role": contribution.role,
            "classification": work.work_type,
            "included": contribution.is_default_included,
            "verified": contribution.review_status in {"verified", "auto_accepted"},
            "identifiers": sorted(identities.get(laureate.id, [])),
        }
    candidate_counts = Counter(str(item["nobel_api_id"]) for item in works.values())
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "works": dict(sorted(works.items())),
        "candidate_counts": dict(sorted(candidate_counts.items())),
    }


def differential_report(
    current: dict[str, object], previous: dict[str, object] | None
) -> dict[str, object]:
    """Describe drift and identify destructive changes to verified records."""

    if previous is None:
        return {
            "baseline": True,
            "added": [],
            "removed": [],
            "changed": [],
            "candidate_count_changes": {},
            "blocking_changes": [],
        }
    current_works = current.get("works", {})
    previous_works = previous.get("works", {})
    if not isinstance(current_works, dict) or not isinstance(previous_works, dict):
        raise ValueError("Audit snapshots must contain a works mapping")
    added = sorted(set(current_works) - set(previous_works))
    removed = sorted(set(previous_works) - set(current_works))
    changed: list[dict[str, object]] = []
    destructive_fields = {"title", "role", "classification", "identifiers", "included"}
    for key in sorted(set(current_works) & set(previous_works)):
        before = previous_works[key]
        after = current_works[key]
        if not isinstance(before, dict) or not isinstance(after, dict):
            continue
        fields = sorted(
            field for field in destructive_fields if before.get(field) != after.get(field)
        )
        if fields:
            changed.append({"review_key": key, "fields": fields, "before": before, "after": after})
    blocking = [
        {"kind": "removed_verified", "review_key": key}
        for key in removed
        if isinstance(previous_works[key], dict) and previous_works[key].get("verified")
    ]
    blocking.extend(
        {"kind": "changed_verified", "review_key": item["review_key"], "fields": item["fields"]}
        for item in changed
        if isinstance(item["before"], dict) and item["before"].get("verified")
    )
    current_counts = current.get("candidate_counts", {})
    previous_counts = previous.get("candidate_counts", {})
    count_changes: dict[str, dict[str, int]] = {}
    if isinstance(current_counts, dict) and isinstance(previous_counts, dict):
        for nobel_id in sorted(set(current_counts) | set(previous_counts)):
            before = int(previous_counts.get(nobel_id, 0))
            after = int(current_counts.get(nobel_id, 0))
            if before != after:
                count_changes[nobel_id] = {"before": before, "after": after}
    return {
        "baseline": False,
        "added": added,
        "removed": removed,
        "changed": changed,
        "candidate_count_changes": count_changes,
        "blocking_changes": blocking,
    }


def _stale_overrides(session: Session, valid_keys: set[str]) -> list[dict[str, object]]:
    stale: list[dict[str, object]] = []
    for override in session.scalars(select(ManualOverride)).all():
        if override.target_type == "contribution" and override.target_key not in valid_keys:
            stale.append(
                {
                    "id": override.id,
                    "target_type": override.target_type,
                    "target_key": override.target_key,
                    "action": override.action,
                    "reason": override.reason,
                }
            )
    return stale


def _regression_results(session: Session, regression_path: Path | None) -> list[dict[str, object]]:
    if regression_path is None or not regression_path.exists():
        return []
    loaded = yaml.safe_load(regression_path.read_text(encoding="utf-8")) or {}
    cases = loaded.get("laureates", []) if isinstance(loaded, dict) else []
    results: list[dict[str, object]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        name = str(case.get("name", ""))
        laureate = session.scalar(select(Laureate).where(Laureate.display_name == name))
        work_count = 0
        if laureate is not None:
            work_count = len(
                session.scalars(
                    select(Contribution).where(Contribution.laureate_id == laureate.id)
                ).all()
            )
        minimum = int(case.get("minimum_candidates", 0))
        maximum_value = case.get("maximum_candidates")
        maximum = int(maximum_value) if isinstance(maximum_value, int) else None
        passed = laureate is not None and work_count >= minimum
        if maximum is not None:
            passed = passed and work_count <= maximum
        results.append(
            {
                "name": name,
                "present": laureate is not None,
                "candidate_count": work_count,
                "passed": passed,
                "audit_note": case.get("audit_note", ""),
            }
        )
    return results


def audit_document(
    session: Session,
    enabled_sources: set[str],
    previous: dict[str, object] | None = None,
    regression_path: Path | None = None,
) -> dict[str, object]:
    """Build a complete audit report without mutating dataset state."""

    snapshot = dataset_snapshot(session)
    works = snapshot["works"]
    if not isinstance(works, dict):
        raise TypeError("Snapshot works must be a mapping")
    laureates = session.scalars(select(Laureate).order_by(Laureate.nobel_api_id)).all()
    candidate_counts = snapshot["candidate_counts"]
    if not isinstance(candidate_counts, dict):
        raise TypeError("Snapshot candidate counts must be a mapping")
    queried: dict[int, set[str]] = defaultdict(set)
    for query in session.scalars(select(DiscoveryQuery)).all():
        queried[query.laureate_id].add(query.source)
    zero_book = [
        {
            "nobel_api_id": laureate.nobel_api_id,
            "name": laureate.display_name,
            "queried_sources": sorted(queried[laureate.id]),
            "missing_sources": sorted(enabled_sources - queried[laureate.id]),
            "disposition": "audited_empty"
            if enabled_sources <= queried[laureate.id]
            else "coverage_incomplete",
        }
        for laureate in laureates
        if int(candidate_counts.get(laureate.nobel_api_id, 0)) == 0
    ]
    incomplete = [
        {
            "nobel_api_id": laureate.nobel_api_id,
            "name": laureate.display_name,
            "missing_sources": sorted(enabled_sources - queried[laureate.id]),
        }
        for laureate in laureates
        if enabled_sources - queried[laureate.id]
    ]
    source_counts = Counter(record.source for record in session.scalars(select(SourceRecord)).all())
    regressions = _regression_results(session, regression_path)
    valid_keys = set(works)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "snapshot": snapshot,
        "differential": differential_report(snapshot, previous),
        "suspicious_gaps": {
            "zero_book_laureates": zero_book,
            "incomplete_source_coverage": incomplete,
        },
        "source_contribution_analysis": dict(sorted(source_counts.items())),
        "stale_overrides": _stale_overrides(session, valid_keys),
        "regression_bibliographies": regressions,
        "incomplete_summary": {
            "zero_book_laureates": len(zero_book),
            "incomplete_source_coverage": len(incomplete),
            "stale_overrides": len(_stale_overrides(session, valid_keys)),
            "failed_regressions": sum(not bool(item["passed"]) for item in regressions),
        },
    }


def write_audit_report(
    session: Session,
    output_path: Path,
    enabled_sources: set[str],
    previous_path: Path | None = None,
    regression_path: Path | None = None,
) -> dict[str, object]:
    previous: dict[str, Any] | None = None
    if previous_path is not None and previous_path.exists():
        loaded = json.loads(previous_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            snapshot = loaded.get("snapshot", loaded)
            previous = snapshot if isinstance(snapshot, dict) else None
    report = audit_document(session, enabled_sources, previous, regression_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return report
