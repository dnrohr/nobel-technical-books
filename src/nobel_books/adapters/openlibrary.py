"""Low-rate structured Open Library API adapter."""

import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from nobel_books.errors import SourceUnavailableError


class AuthorSearchDocument(BaseModel):
    model_config = ConfigDict(extra="allow")

    key: str
    name: str
    alternate_names: list[str] = Field(default_factory=list)
    birth_date: str | None = None
    death_date: str | None = None


class AuthorSearchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    docs: list[AuthorSearchDocument] = Field(default_factory=list)


class OpenLibraryFetch(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    kind: str
    parent_id: str | None = None
    url: str
    status_code: int
    content: bytes
    payload: dict[str, Any]


class OpenLibraryAdapter:
    """Resolve authors and traverse author works and work editions."""

    name = "openlibrary"

    def __init__(
        self,
        base_url: str,
        user_agent: str,
        *,
        requests_per_second: float = 0.5,
        page_size: int = 50,
        client: httpx.Client | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.page_size = page_size
        self._client = client
        self._sleeper = sleeper
        self._clock = clock
        self._minimum_interval = 1 / requests_per_second
        self._last_request_at: float | None = None

    def _throttle(self) -> None:
        if self._last_request_at is not None:
            remaining = self._minimum_interval - (self._clock() - self._last_request_at)
            if remaining > 0:
                self._sleeper(remaining)

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        reraise=True,
    )
    def _request(
        self, client: httpx.Client, path: str, params: dict[str, str | int]
    ) -> httpx.Response:
        self._throttle()
        try:
            response = client.get(
                f"{self.base_url}{path}",
                params=params,
                headers={
                    "Accept": "application/json",
                    "User-Agent": self.user_agent,
                },
            )
            response.raise_for_status()
            return response
        finally:
            self._last_request_at = self._clock()

    def _fetch(
        self,
        client: httpx.Client,
        kind: str,
        path: str,
        params: dict[str, str | int],
        parent_id: str | None = None,
    ) -> OpenLibraryFetch:
        try:
            response = self._request(client, path, params)
            payload: Any = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Open Library response root is not an object")
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceUnavailableError(f"Open Library {kind} request failed") from exc
        return OpenLibraryFetch(
            kind=kind,
            parent_id=parent_id,
            url=str(response.request.url),
            status_code=response.status_code,
            content=response.content,
            payload=payload,
        )

    def search_author(self, name: str) -> OpenLibraryFetch:
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=60.0, follow_redirects=True)
        try:
            return self._fetch(
                client,
                "author_search",
                "/search/authors.json",
                {"q": name, "limit": 20},
            )
        finally:
            if owns_client:
                client.close()

    def author_works(self, author_id: str) -> Iterator[OpenLibraryFetch]:
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=60.0, follow_redirects=True)
        offset = 0
        try:
            while True:
                fetched = self._fetch(
                    client,
                    "author_works",
                    f"/authors/{author_id}/works.json",
                    {"limit": self.page_size, "offset": offset},
                    author_id,
                )
                yield fetched
                entries = fetched.payload.get("entries", [])
                size = int(fetched.payload.get("size", len(entries)))
                if not isinstance(entries, list) or not entries or offset + len(entries) >= size:
                    break
                offset += len(entries)
        finally:
            if owns_client:
                client.close()

    def work_editions(self, work_id: str) -> Iterator[OpenLibraryFetch]:
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=60.0, follow_redirects=True)
        offset = 0
        try:
            while True:
                fetched = self._fetch(
                    client,
                    "work_editions",
                    f"/works/{work_id}/editions.json",
                    {"limit": self.page_size, "offset": offset},
                    work_id,
                )
                yield fetched
                entries = fetched.payload.get("entries", [])
                size = int(fetched.payload.get("size", len(entries)))
                if not isinstance(entries, list) or not entries or offset + len(entries) >= size:
                    break
                offset += len(entries)
        finally:
            if owns_client:
                client.close()
