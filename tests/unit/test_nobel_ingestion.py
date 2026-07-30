import json
from pathlib import Path

import httpx
import respx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nobel_books.adapters.nobel import NobelApiAdapter
from nobel_books.cache import RawResponseCache
from nobel_books.db import make_engine, upgrade_database
from nobel_books.models.database import Laureate, PipelineRun, PrizeAward, SourceFetch
from nobel_books.pipeline.laureates import sync_laureates


def fixture(name: str) -> dict[str, object]:
    path = Path(__file__).parents[1] / "fixtures" / "nobel" / name
    return json.loads(path.read_text(encoding="utf-8"))


@respx.mock
def test_sync_handles_pagination_organizations_and_duplicate_prizes(tmp_path: Path) -> None:
    responses = [
        httpx.Response(200, json=fixture(page))
        for page in ("page_1.json", "page_2.json", "page_1.json", "page_2.json")
    ]
    route = respx.get("https://api.example/laureates").mock(side_effect=responses)
    database_url = f"sqlite:///{tmp_path / 'test.sqlite3'}"
    upgrade_database(database_url)
    engine = make_engine(database_url)
    adapter = NobelApiAdapter("https://api.example", page_size=2)

    with Session(engine) as session:
        first = sync_laureates(session, adapter, RawResponseCache(tmp_path / "cache"))
    with Session(engine) as session:
        second = sync_laureates(session, adapter, RawResponseCache(tmp_path / "cache"))
        laureates = session.scalars(select(Laureate).order_by(Laureate.nobel_api_id)).all()
        awards = session.scalars(select(PrizeAward).order_by(PrizeAward.year)).all()
        fetch_count = session.scalar(select(func.count()).select_from(SourceFetch))
        run_count = session.scalar(select(func.count()).select_from(PipelineRun))

    assert route.call_count == 4
    assert first.laureates == second.laureates == 2
    assert first.organizations_skipped == 1
    assert first.awards_by_category == {"physics": 1, "chemistry": 1, "medicine": 1}
    assert [laureate.display_name for laureate in laureates] == ["Marie Curie", "Ada Example"]
    assert [(award.category, award.year) for award in awards] == [
        ("physics", 1903),
        ("chemistry", 1911),
        ("medicine", 1950),
    ]
    assert fetch_count == 2
    assert run_count == 2
    assert len(list((tmp_path / "cache" / "nobel").glob("*.json"))) == 2
    engine.dispose()
