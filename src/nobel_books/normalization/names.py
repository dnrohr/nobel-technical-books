"""Person name matching keys."""

import re
import unicodedata

PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
WHITESPACE = re.compile(r"\s+")


def normalize_name(value: str) -> str:
    """Create a conservative Unicode-preserving matching key."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = PUNCTUATION.sub(" ", normalized)
    return WHITESPACE.sub(" ", normalized).strip()
