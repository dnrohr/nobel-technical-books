"""Batched Wikidata SPARQL identity adapter."""

import json
from collections.abc import Iterator, Sequence
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from nobel_books.errors import SourceUnavailableError

IDENTIFIER_PROPERTIES = {
    "orcid": "P496",
    "viaf": "P214",
    "isni": "P213",
    "gnd": "P227",
    "lcnaf": "P244",
    "openlibrary": "P648",
}


class BindingValue(BaseModel):
    model_config = ConfigDict(extra="ignore")

    value: str
    language: str | None = Field(default=None, alias="xml:lang")


class SparqlResults(BaseModel):
    model_config = ConfigDict(extra="ignore")

    bindings: list[dict[str, BindingValue]] = Field(default_factory=list)


class SparqlResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: SparqlResults


class FetchedBindings(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    url: str
    status_code: int
    content: bytes
    bindings: list[dict[str, BindingValue]]
    nobel_ids: list[str]


def _chunks(values: Sequence[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(values), size):
        yield list(values[start : start + size])


def identity_query(nobel_ids: Sequence[str]) -> str:
    values = " ".join(json.dumps(value) for value in nobel_ids)
    optional_ids = "\n".join(
        f"OPTIONAL {{ ?person wdt:{property_id} ?{scheme} . }}"
        for scheme, property_id in IDENTIFIER_PROPERTIES.items()
    )
    return f"""
SELECT ?nobelId ?person ?personLabel ?altLabel {" ".join(f"?{x}" for x in IDENTIFIER_PROPERTIES)}
WHERE {{
  VALUES ?nobelId {{ {values} }}
  ?person wdt:P8024 ?nobelId .
  OPTIONAL {{ ?person skos:altLabel ?altLabel . FILTER(LANG(?altLabel) = "en") }}
  {optional_ids}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
""".strip()


def candidate_query(person_qids: Sequence[str]) -> str:
    values = " ".join(f"wd:{qid}" for qid in person_qids)
    return f"""
SELECT DISTINCT ?person ?item ?itemLabel ?explicitItemLabel ?instance ?instanceLabel ?role
  ?publicationDate ?isbn13 ?isbn10 ?oclc ?editionOf ?editionOfLabel
WHERE {{
  VALUES ?person {{ {values} }}
  {{
    ?item wdt:P50 ?person .
    BIND("author" AS ?role)
  }}
  UNION
  {{
    ?item wdt:P98 ?person .
    BIND("editor" AS ?role)
  }}
  OPTIONAL {{ ?item wdt:P31 ?instance . }}
  OPTIONAL {{
    ?item rdfs:label ?explicitItemLabel .
    FILTER(LANG(?explicitItemLabel) = "en")
  }}
  OPTIONAL {{ ?item wdt:P577 ?publicationDate . }}
  OPTIONAL {{ ?item wdt:P212 ?isbn13 . }}
  OPTIONAL {{ ?item wdt:P957 ?isbn10 . }}
  OPTIONAL {{ ?item wdt:P243 ?oclc . }}
  OPTIONAL {{ ?item wdt:P629 ?editionOf . }}
  SERVICE wikibase:label {{
    bd:serviceParam wikibase:language "en,[AUTO_LANGUAGE]".
  }}
}}
""".strip()


class WikidataIdentityAdapter:
    """Resolve Nobel IDs through exact Wikidata P8024 statements."""

    name = "wikidata"

    def __init__(
        self,
        endpoint: str,
        user_agent: str,
        *,
        batch_size: int = 25,
        client: httpx.Client | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.user_agent = user_agent
        self.batch_size = batch_size
        self._client = client

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        reraise=True,
    )
    def _request(self, client: httpx.Client, batch: list[str]) -> httpx.Response:
        response = client.get(
            self.endpoint,
            params={"query": identity_query(batch), "format": "json"},
            headers={
                "Accept": "application/sparql-results+json",
                "User-Agent": self.user_agent,
            },
        )
        response.raise_for_status()
        return response

    def batches(self, nobel_ids: Sequence[str]) -> Iterator[FetchedBindings]:
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=120.0, follow_redirects=True)
        try:
            for batch in _chunks(nobel_ids, self.batch_size):
                try:
                    response = self._request(client, batch)
                    payload: Any = response.json()
                    parsed = SparqlResponse.model_validate(payload)
                except (httpx.HTTPError, ValueError) as exc:
                    raise SourceUnavailableError(
                        f"Wikidata identity query failed for {len(batch)} Nobel IDs"
                    ) from exc
                yield FetchedBindings(
                    url=str(response.request.url),
                    status_code=response.status_code,
                    content=response.content,
                    bindings=parsed.results.bindings,
                    nobel_ids=batch,
                )
        finally:
            if owns_client:
                client.close()


class WikidataBookAdapter:
    """Discover authored and edited source-native candidate records."""

    name = "wikidata"

    def __init__(
        self,
        endpoint: str,
        user_agent: str,
        *,
        batch_size: int = 10,
        client: httpx.Client | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.user_agent = user_agent
        self.batch_size = batch_size
        self._client = client

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        reraise=True,
    )
    def _request(self, client: httpx.Client, batch: list[str]) -> httpx.Response:
        response = client.get(
            self.endpoint,
            params={"query": candidate_query(batch), "format": "json"},
            headers={
                "Accept": "application/sparql-results+json",
                "User-Agent": self.user_agent,
            },
        )
        response.raise_for_status()
        return response

    def batches(self, qids: Sequence[str]) -> Iterator[FetchedBindings]:
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=120.0, follow_redirects=True)
        try:
            for batch in _chunks(qids, self.batch_size):
                try:
                    response = self._request(client, batch)
                    payload: Any = response.json()
                    parsed = SparqlResponse.model_validate(payload)
                except (httpx.HTTPError, ValueError) as exc:
                    raise SourceUnavailableError(
                        f"Wikidata candidate query failed for {len(batch)} people"
                    ) from exc
                yield FetchedBindings(
                    url=str(response.request.url),
                    status_code=response.status_code,
                    content=response.content,
                    bindings=parsed.results.bindings,
                    nobel_ids=batch,
                )
        finally:
            if owns_client:
                client.close()
