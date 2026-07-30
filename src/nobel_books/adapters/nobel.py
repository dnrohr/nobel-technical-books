"""Nobel Prize API adapter."""

from collections.abc import Iterator
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from nobel_books.errors import SourceUnavailableError


class LocalizedText(BaseModel):
    """A Nobel API localized text object."""

    model_config = ConfigDict(extra="ignore")

    en: str | None = None


class LifeEvent(BaseModel):
    """Birth or death metadata."""

    model_config = ConfigDict(extra="ignore")

    date: str | None = None


class NobelPrize(BaseModel):
    """Prize data embedded in a laureate response."""

    model_config = ConfigDict(extra="ignore")

    award_year: str = Field(alias="awardYear")
    category: LocalizedText
    motivation: LocalizedText | None = None
    prize_amount_share: str | None = Field(default=None, alias="prizeAmountShare")


class NobelLaureate(BaseModel):
    """A person or organization returned by the Nobel API."""

    model_config = ConfigDict(extra="ignore")

    id: str
    known_name: LocalizedText | None = Field(default=None, alias="knownName")
    given_name: LocalizedText | None = Field(default=None, alias="givenName")
    family_name: LocalizedText | None = Field(default=None, alias="familyName")
    full_name: LocalizedText | None = Field(default=None, alias="fullName")
    org_name: LocalizedText | None = Field(default=None, alias="orgName")
    gender: str | None = None
    birth: LifeEvent | None = None
    death: LifeEvent | None = None
    nobel_prizes: list[NobelPrize] = Field(default_factory=list, alias="nobelPrizes")

    @property
    def is_organization(self) -> bool:
        return self.org_name is not None

    @property
    def display_name(self) -> str:
        candidates = (self.known_name, self.full_name, self.org_name)
        return next((item.en for item in candidates if item and item.en), self.id)


class PageMeta(BaseModel):
    """Nobel API pagination metadata."""

    model_config = ConfigDict(extra="ignore")

    offset: int = 0
    limit: int = 0
    count: int = 0


class LaureatePage(BaseModel):
    """One parsed laureate response page."""

    model_config = ConfigDict(extra="ignore")

    laureates: list[NobelLaureate] = Field(default_factory=list)
    meta: PageMeta = Field(default_factory=PageMeta)


class FetchedPage(BaseModel):
    """Parsed response plus immutable fetch data."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    url: str
    params: dict[str, int]
    status_code: int
    headers: dict[str, str]
    content: bytes
    page: LaureatePage


class NobelApiAdapter:
    """Retrieve all laureates from the official paginated API."""

    name = "nobel"

    def __init__(
        self,
        base_url: str,
        *,
        page_size: int = 100,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.page_size = page_size
        self._client = client

    def pages(self) -> Iterator[FetchedPage]:
        offset = 0
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=30.0, follow_redirects=True)
        try:
            while True:
                params = {"offset": offset, "limit": self.page_size}
                try:
                    response = client.get(f"{self.base_url}/laureates", params=params)
                    response.raise_for_status()
                    payload: Any = response.json()
                    page = LaureatePage.model_validate(payload)
                except (httpx.HTTPError, ValueError) as exc:
                    raise SourceUnavailableError(
                        f"Nobel API request failed at offset {offset}"
                    ) from exc

                yield FetchedPage(
                    url=str(response.request.url),
                    params=params,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    content=response.content,
                    page=page,
                )

                received = len(page.laureates)
                total = page.meta.count
                if received == 0 or offset + received >= total:
                    break
                offset += received
        finally:
            if owns_client:
                client.close()
