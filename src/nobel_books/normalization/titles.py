"""Title normalization that preserves meaningful symbols."""

import re
import unicodedata

WHITESPACE = re.compile(r"\s+")


def normalize_title(value: str) -> str:
    """Normalize Unicode, case, punctuation, and whitespace for comparison."""

    value = unicodedata.normalize("NFKC", value).casefold()
    characters = [
        " " if unicodedata.category(character).startswith("P") else character for character in value
    ]
    return WHITESPACE.sub(" ", "".join(characters)).strip()
