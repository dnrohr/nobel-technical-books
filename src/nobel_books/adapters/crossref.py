"""Crossref polite-pool type discovery and DOI enrichment."""

import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from nobel_books.errors import SourceUnavailableError

BOOK_TYPES = {
    "book",
    "book-set",
    "edited-book",
    "monograph",
    "reference-book",
}


class CrossrefFetch(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    kind: str
    parent_id: str | None = None
    url: str
    status_code: int
    content: bytes
    message: Any


class CrossrefAdapter:
    """Use Crossref's polite pool to discover types and corroborate DOIs."""

    name = "crossref"

    def __init__(
        self,
        base_url: str,
        contact_email: str,
        *,
        user_agent: str,
        requests_per_second: float = 1.0,
        client: httpx.Client | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.contact_email = contact_email
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
    def _request(self, client: httpx.Client, path: str) -> httpx.Response:
        self._throttle()
        try:
            response = client.get(
                f"{self.base_url}{path}",
                params={"mailto": self.contact_email},
                headers={"User-Agent": f"{self.user_agent} mailto:{self.contact_email}"},
            )
            response.raise_for_status()
            return response
        finally:
            self._last_request_at = self._clock()

    def _fetch(self, kind: str, path: str, parent_id: str | None = None) -> CrossrefFetch:
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=60.0, follow_redirects=True)
        try:
            try:
                response = self._request(client, path)
                payload: Any = response.json()
                parsed = CrossrefEnvelope.model_validate(payload)
            except (httpx.HTTPError, ValueError) as exc:
                raise SourceUnavailableError(f"Crossref {kind} request failed") from exc
            return CrossrefFetch(
                kind=kind,
                parent_id=parent_id,
                url=str(response.request.url),
                status_code=response.status_code,
                content=response.content,
                message=parsed.message,
            )
        finally:
            if owns_client:
                client.close()

    def types(self) -> CrossrefFetch:
        return self._fetch("types", "/types")

    def doi(self, doi: str) -> CrossrefFetch:
        return self._fetch("doi", f"/works/{quote(doi, safe='')}", doi)


class CrossrefEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: Any = Field(default_factory=dict)
