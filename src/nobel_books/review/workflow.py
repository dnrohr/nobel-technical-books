"""Stable contribution review CSV workflow."""

import csv
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from nobel_books.models.database import (
    CanonicalWork,
    Contribution,
    Laureate,
    ManualOverride,
)


def contribution_review_key(laureate: Laureate, work: CanonicalWork, role: str) -> str:
    return f"{laureate.nobel_api_id}::{work.cluster_key}::{role}"


def review_queue_items(session: Session) -> list[dict[str, object]]:
    rows = session.execute(
        select(Contribution, Laureate, CanonicalWork)
        .join(Laureate, Laureate.id == Contribution.laureate_id)
        .join(CanonicalWork, CanonicalWork.id == Contribution.canonical_work_id)
        .where(
            (Contribution.review_status.in_(("needs_review", "rejected")))
            | (CanonicalWork.review_status == "needs_review")
        )
        .order_by(Laureate.display_name, CanonicalWork.preferred_title)
    ).all()
    items: list[dict[str, object]] = []
    for contribution, laureate, work in rows:
        flags = []
        if contribution.relationship_confidence < 0.75:
            flags.append("low_relationship_confidence")
        if (work.classification_confidence or 0) < 0.75:
            flags.append("low_classification_confidence")
        items.append(
            {
                "review_key": contribution_review_key(laureate, work, contribution.role),
                "nobel_api_id": laureate.nobel_api_id,
                "laureate_name": laureate.display_name,
                "candidate_title": work.preferred_title,
                "candidate_role": contribution.role,
                "classification": work.work_type,
                "technicality_score": work.technicality_score,
                "classification_confidence": work.classification_confidence,
                "relationship_confidence": contribution.relationship_confidence,
                "relationship_status": contribution.review_status,
                "warning_flags": "|".join(flags),
            }
        )
    return items


def export_review_queue(session: Session, path: Path) -> int:
    items = review_queue_items(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "review_key",
                "nobel_api_id",
                "laureate_name",
                "candidate_title",
                "candidate_role",
                "classification",
                "technicality_score",
                "classification_confidence",
                "relationship_confidence",
                "relationship_status",
                "warning_flags",
                "reviewer_decision",
                "reviewer_reason",
                "reviewer",
            ]
        )
        for item in items:
            writer.writerow(
                [
                    item["review_key"],
                    item["nobel_api_id"],
                    item["laureate_name"],
                    item["candidate_title"],
                    item["candidate_role"],
                    item["classification"],
                    item["technicality_score"],
                    item["classification_confidence"],
                    item["relationship_confidence"],
                    item["relationship_status"],
                    item["warning_flags"],
                    "",
                    "",
                    "",
                ]
            )
    return len(items)


def record_review_decision(
    session: Session,
    target_key: str,
    decision: str,
    reason: str,
    reviewer: str | None = None,
) -> ManualOverride:
    normalized_decision = decision.strip().casefold()
    if normalized_decision not in {"accept", "reject"}:
        raise ValueError(f"Unsupported reviewer decision: {normalized_decision}")
    if not reason.strip():
        raise ValueError("Every reviewer decision requires a reason")
    if target_key.count("::") != 2:
        raise ValueError(f"Invalid stable review key: {target_key}")
    action = "include" if normalized_decision == "accept" else "exclude"
    override = session.scalar(
        select(ManualOverride).where(
            ManualOverride.target_type == "contribution",
            ManualOverride.target_key == target_key,
            ManualOverride.action == action,
        )
    )
    if override is None:
        override = ManualOverride(
            target_type="contribution",
            target_key=target_key,
            action=action,
        )
        session.add(override)
    override.payload_json = {"decision": normalized_decision}
    override.reason = reason.strip()
    override.reviewer = reviewer.strip() if reviewer and reviewer.strip() else None
    override.created_at = datetime.now(UTC)
    return override


def import_review_decisions(session: Session, path: Path) -> int:
    count = 0
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            decision = (row.get("reviewer_decision") or "").strip().casefold()
            if not decision:
                continue
            reason = (row.get("reviewer_reason") or "").strip()
            target_key = (row.get("review_key") or "").strip()
            try:
                record_review_decision(
                    session,
                    target_key,
                    decision,
                    reason,
                    row.get("reviewer"),
                )
            except ValueError as exc:
                if "requires a reason" in str(exc):
                    raise ValueError("Every reviewer decision requires reviewer_reason") from exc
                raise
            count += 1
    session.commit()
    return count
