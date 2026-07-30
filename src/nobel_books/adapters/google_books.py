"""Google Books candidate discovery adapter."""

import time
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from nobel_books.errors import SourceUnavailableError


class GoogleVolume(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    volume_info: dict[str, Any] = Field(default_factory=dict, alias="volumeInfo")


class GoogleBooksResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total_items: int = Field(default=0, alias="totalItems")
    items: list[GoogleVolume] = Field(default_factory=list)


class GoogleBooksFetch(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    query: str
    variant_type: str
    start_index: int
    url: str
    status_code: int
    content: bytes
    response: GoogleBooksResponse


def redact_api_key(url: str) -> str:
    parts = urlsplit(url)
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parts.query)
            if key.casefold() not in {"key", "api_key"}
        ]
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


class GoogleBooksAdapter:
    """Run controlled, book-only, safely bounded author queries."""

    name = "google_books"

    def __init__(
        self,
        base_url: str,
        user_agent: str,
        *,
        api_key: str | None = None,
        requests_per_second: float = 2.0,
        page_size: int = 40,
        max_results_per_query: int = 400,
        client: httpx.Client | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.api_key = api_key
        self.page_size = min(page_size, 40)
        self.max_results_per_query = max_results_per_query
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
    def _request(self, client: httpx.Client, query: str, start_index: int) -> httpx.Response:
        params: dict[str, str | int] = {
            "q": query,
            "printType": "books",
            "projection": "full",
            "maxResults": self.page_size,
            "startIndex": start_index,
        }
        if self.api_key:
            params["key"] = self.api_key
        self._throttle()
        try:
            response = client.get(
                f"{self.base_url}/volumes",
                params=params,
                headers={"User-Agent": self.user_agent, "Accept": "application/json"},
            )
            response.raise_for_status()
            return response
        finally:
            self._last_request_at = self._clock()

    def volumes(self, query: str, variant_type: str) -> Iterator[GoogleBooksFetch]:
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=60.0, follow_redirects=True)
        start_index = 0
        try:
            while start_index < self.max_results_per_query:
                try:
                    response = self._request(client, query, start_index)
                    payload: Any = response.json()
                    parsed = GoogleBooksResponse.model_validate(payload)
                except (httpx.HTTPError, ValueError) as exc:
                    raise SourceUnavailableError("Google Books query failed") from exc
                yield GoogleBooksFetch(
                    query=query,
                    variant_type=variant_type,
                    start_index=start_index,
                    url=redact_api_key(str(response.request.url)),
                    status_code=response.status_code,
                    content=response.content,
                    response=parsed,
                )
                received = len(parsed.items)
                ceiling = min(parsed.total_items, self.max_results_per_query)
                if received == 0 or start_index + received >= ceiling:
                    break
                start_index += received
        finally:
            if owns_client:
                client.close()
