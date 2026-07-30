"""Identifier-first OpenAlex author and book adapter."""

import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from nobel_books.adapters.google_books import redact_api_key
from nobel_books.errors import SourceUnavailableError


class OpenAlexResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    results: list[dict[str, Any]] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class OpenAlexFetch(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    kind: str
    parent_id: str | None = None
    url: str
    status_code: int
    content: bytes
    response: OpenAlexResponse


class OpenAlexAdapter:
    """Resolve ORCIDs and retrieve OpenAlex works filtered to books."""

    name = "openalex"

    def __init__(
        self,
        base_url: str,
        contact_email: str,
        *,
        api_key: str | None = None,
        include_xpac: bool = False,
        requests_per_second: float = 1.0,
        page_size: int = 100,
        client: httpx.Client | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.contact_email = contact_email
        self.api_key = api_key
        self.include_xpac = include_xpac
        self.page_size = min(page_size, 200)
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
    def _request(
        self, client: httpx.Client, path: str, params: dict[str, str | int | bool]
    ) -> httpx.Response:
        params = {**params, "mailto": self.contact_email}
        if self.api_key:
            params["api_key"] = self.api_key
        self._throttle()
        try:
            response = client.get(f"{self.base_url}{path}", params=params)
            response.raise_for_status()
            return response
        finally:
            self._last_request_at = self._clock()

    def _fetch(
        self,
        client: httpx.Client,
        kind: str,
        path: str,
        params: dict[str, str | int | bool],
        parent_id: str | None = None,
    ) -> OpenAlexFetch:
        try:
            response = self._request(client, path, params)
            payload: Any = response.json()
            parsed = OpenAlexResponse.model_validate(payload)
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceUnavailableError(f"OpenAlex {kind} request failed") from exc
        return OpenAlexFetch(
            kind=kind,
            parent_id=parent_id,
            url=redact_api_key(str(response.request.url)),
            status_code=response.status_code,
            content=response.content,
            response=parsed,
        )

    def resolve_orcid(self, orcid: str) -> OpenAlexFetch:
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=60.0, follow_redirects=True)
        try:
            return self._fetch(
                client,
                "author",
                "/authors",
                {"filter": f"orcid:https://orcid.org/{orcid}"},
                orcid,
            )
        finally:
            if owns_client:
                client.close()

    def books(self, author_id: str) -> Iterator[OpenAlexFetch]:
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=60.0, follow_redirects=True)
        cursor = "*"
        try:
            while cursor:
                fetched = self._fetch(
                    client,
                    "works",
                    "/works",
                    {
                        "filter": f"authorships.author.id:{author_id},type:book",
                        "per-page": self.page_size,
                        "cursor": cursor,
                        "include_xpac": str(self.include_xpac).lower(),
                    },
                    author_id,
                )
                yield fetched
                next_cursor = fetched.response.meta.get("next_cursor")
                cursor = next_cursor if isinstance(next_cursor, str) else ""
                if not fetched.response.results:
                    break
        finally:
            if owns_client:
                client.close()
