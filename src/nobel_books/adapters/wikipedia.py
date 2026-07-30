"""MediaWiki Action API adapter for bibliography fallback sections."""

import time
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from nobel_books.errors import SourceUnavailableError


class WikipediaFetch(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    kind: str
    page_title: str
    section_index: str | None = None
    url: str
    status_code: int
    content: bytes
    payload: dict[str, Any]


class WikipediaAdapter:
    """Fetch page section metadata and individual relevant sections only."""

    name = "wikipedia"

    def __init__(
        self,
        endpoint: str,
        user_agent: str,
        *,
        requests_per_second: float = 0.5,
        client: httpx.Client | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.endpoint = endpoint
        self.user_agent = user_agent
        self._client = client
        self._sleeper = sleeper
        self._clock = clock
        self._minimum_interval = 1 / requests_per_second
        self._last_request_at: float | None = None

    def _throttle(self) -> None:
        if self._last_request_at is not None:
            wait = self._minimum_interval - (self._clock() - self._last_request_at)
            if wait > 0:
                self._sleeper(wait)

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        reraise=True,
    )
    def _request(self, client: httpx.Client, params: dict[str, str]) -> httpx.Response:
        self._throttle()
        try:
            response = client.get(
                self.endpoint,
                params={"format": "json", "formatversion": "2", **params},
                headers={"User-Agent": self.user_agent},
            )
            response.raise_for_status()
            return response
        finally:
            self._last_request_at = self._clock()

    def _fetch(
        self,
        kind: str,
        page_title: str,
        params: dict[str, str],
        section_index: str | None = None,
    ) -> WikipediaFetch:
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=60.0, follow_redirects=True)
        try:
            try:
                response = self._request(client, params)
                payload: Any = response.json()
                if not isinstance(payload, dict) or not isinstance(payload.get("parse"), dict):
                    raise ValueError("MediaWiki parse payload missing")
            except (httpx.HTTPError, ValueError) as exc:
                raise SourceUnavailableError(
                    f"Wikipedia {kind} request failed for {page_title}"
                ) from exc
            return WikipediaFetch(
                kind=kind,
                page_title=page_title,
                section_index=section_index,
                url=str(response.request.url),
                status_code=response.status_code,
                content=response.content,
                payload=payload,
            )
        finally:
            if owns_client:
                client.close()

    def sections(self, page_title: str) -> WikipediaFetch:
        return self._fetch(
            "sections",
            page_title,
            {
                "action": "parse",
                "page": page_title,
                "prop": "sections",
                "redirects": "1",
            },
        )

    def section(self, page_title: str, section_index: str) -> WikipediaFetch:
        return self._fetch(
            "section",
            page_title,
            {
                "action": "parse",
                "page": page_title,
                "prop": "wikitext",
                "section": section_index,
                "redirects": "1",
            },
            section_index,
        )
