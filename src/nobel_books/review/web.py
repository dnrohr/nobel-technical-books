"""Minimal local review interface backed by standard manual overrides."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from nobel_books.classification.classifier import score_relationships
from nobel_books.review.workflow import record_review_decision, review_queue_items

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport"
content="width=device-width,initial-scale=1"><title>Nobel Books Review</title>
<style>
body{font:16px system-ui;max-width:1050px;margin:2rem auto;padding:0 1rem;color:#18202a}
article{border:1px solid #ccd3db;border-radius:8px;padding:1rem;margin:1rem 0}
.meta{color:#52606d}.actions{display:flex;gap:.5rem;flex-wrap:wrap;margin-top:.8rem}
input{min-width:28rem;padding:.5rem}button{padding:.5rem .8rem}button.reject{color:#9b1c1c}
</style></head><body><h1>Contribution review</h1>
<p>Decisions are saved as the same durable manual overrides used by CSV import.</p>
<main id="queue">Loading…</main><script>
const queue=document.querySelector("#queue");
async function load(){const rows=await (await fetch("/api/review?limit=100")).json();
 queue.textContent=""; for(const row of rows){const card=document.createElement("article");
 const title=document.createElement("h2");title.textContent=row.candidate_title;card.append(title);
 const meta=document.createElement("p");meta.className="meta";
 meta.textContent=`${row.laureate_name} · ${row.candidate_role} · `
  +`${row.classification} · confidence ${row.relationship_confidence}`;
 card.append(meta);const box=document.createElement("div");box.className="actions";
 const reason=document.createElement("input");reason.placeholder="Required decision reason";
 const reviewer=document.createElement("input");reviewer.placeholder="Reviewer (optional)";
 reviewer.style.minWidth="12rem";box.append(reason,reviewer);
 for(const decision of ["accept","reject"]){const button=document.createElement("button");
 button.textContent=decision;button.className=decision;
 button.onclick=async()=>{const response=await fetch("/api/decision",{method:"POST",
 headers:{"Content-Type":"application/json"},body:JSON.stringify({review_key:row.review_key,
 decision,reason:reason.value,reviewer:reviewer.value||null})});
 if(response.ok){card.remove()}else{alert((await response.json()).detail)}};box.append(button)}
 card.append(box);queue.append(card)}}load();
</script></body></html>"""


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_key: str
    decision: str
    reason: str = Field(min_length=1)
    reviewer: str | None = None


def create_review_app(engine: Engine) -> FastAPI:
    """Create a local ASGI app; callers choose the bind address."""

    application = FastAPI(title="Nobel Books Review", docs_url=None, redoc_url=None)

    def database_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    @application.get("/", response_class=HTMLResponse)
    def index() -> str:
        return PAGE

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
