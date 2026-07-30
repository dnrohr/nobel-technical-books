"""Optional WorldCat Search API 2.0 client using OAuth bearer tokens."""

import time
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from nobel_books.errors import ConfigurationError, SourceUnavailableError


class WorldCatSearchResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    number_of_records: int = Field(default=0, alias="numberOfRecords")
    brief_records: list[dict[str, Any]] = Field(default_factory=list, alias="briefRecords")


class WorldCatAdapter:
    """Search structured WorldCat v2 records; HTML endpoints are never used."""

    name = "worldcat"

    def __init__(
        self,
        base_url: str,
        access_token: str | None,
        *,
        requests_per_second: float = 0.5,
        client: httpx.Client | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not access_token:
            raise ConfigurationError(
                "WorldCat is optional and requires an OAuth access token; source remains disabled"
            )
        self.base_url = base_url.rstrip("/")
        self._access_token = access_token
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
    def _request(self, client: httpx.Client, query: str, limit: int) -> httpx.Response:
        self._throttle()
        try:
            response = client.get(
                f"{self.base_url}/worldcat/search/v2/bibs",
                params={"q": query, "itemType": "book", "limit": min(limit, 50)},
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
            return response
        finally:
            self._last_request_at = self._clock()

    def search(self, query: str, *, limit: int = 20) -> WorldCatSearchResponse:
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=60.0, follow_redirects=False)
        try:
            try:
                response = self._request(client, query, limit)
                payload: Any = response.json()
                return WorldCatSearchResponse.model_validate(payload)
            except (httpx.HTTPError, ValueError) as exc:
                raise SourceUnavailableError("WorldCat Search API query failed") from exc
        finally:
            if owns_client:
                client.close()
