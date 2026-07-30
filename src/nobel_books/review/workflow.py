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


def export_review_queue(session: Session, path: Path) -> int:
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
        for contribution, laureate, work in rows:
            flags = []
            if contribution.relationship_confidence < 0.75:
                flags.append("low_relationship_confidence")
            if (work.classification_confidence or 0) < 0.75:
                flags.append("low_classification_confidence")
            writer.writerow(
                [
                    contribution_review_key(laureate, work, contribution.role),
                    laureate.nobel_api_id,
                    laureate.display_name,
                    work.preferred_title,
                    contribution.role,
                    work.work_type,
                    work.technicality_score,
                    work.classification_confidence,
                    contribution.relationship_confidence,
                    contribution.review_status,
                    "|".join(flags),
                    "",
                    "",
                    "",
                ]
            )
    return len(rows)


def import_review_decisions(session: Session, path: Path) -> int:
    count = 0
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            decision = (row.get("reviewer_decision") or "").strip().casefold()
            if not decision:
                continue
            if decision not in {"accept", "reject"}:
                raise ValueError(f"Unsupported reviewer decision: {decision}")
            reason = (row.get("reviewer_reason") or "").strip()
            if not reason:
                raise ValueError("Every reviewer decision requires reviewer_reason")
            target_key = (row.get("review_key") or "").strip()
            if target_key.count("::") != 2:
                raise ValueError(f"Invalid stable review key: {target_key}")
            action = "include" if decision == "accept" else "exclude"
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
            override.payload_json = {"decision": decision}
            override.reason = reason
            override.reviewer = (row.get("reviewer") or "").strip() or None
            override.created_at = datetime.now(UTC)
            count += 1
    session.commit()
    return count
