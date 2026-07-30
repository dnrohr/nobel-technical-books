"""Conservative parsing for partial and uncertain publication dates."""

import re
from dataclasses import dataclass

YEAR = re.compile(r"(?<!\d)(1[0-9]{3}|20[0-9]{2})(?!\d)")


@dataclass(frozen=True)
class ParsedDate:
    raw: str
    lower_year: int | None
    upper_year: int | None
    uncertain: bool


def parse_date(value: str | None) -> ParsedDate:
    raw = (value or "").strip()
    years = [int(match) for match in YEAR.findall(raw)]
    return ParsedDate(
        raw=raw,
        lower_year=min(years) if years else None,
        upper_year=max(years) if years else None,
        uncertain=bool(re.search(r"\b(circa|ca\.?|c\.)\b|\?", raw, re.IGNORECASE)),
    )
