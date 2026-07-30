"""Language code normalization."""

LANGUAGES = {
    "eng": "en",
    "en": "en",
    "english": "en",
    "fre": "fr",
    "fra": "fr",
    "fr": "fr",
    "french": "fr",
    "ger": "de",
    "deu": "de",
    "de": "de",
    "german": "de",
    "spa": "es",
    "es": "es",
    "spanish": "es",
}


def normalize_language(value: str | None) -> str | None:
    if not value:
        return None
    key = value.rsplit("/", 1)[-1].strip().casefold()
    return LANGUAGES.get(key, key or None)
