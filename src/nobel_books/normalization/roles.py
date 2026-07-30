"""Contributor role normalization."""

ROLE_MAP = {
    "author": "author",
    "writer": "author",
    "coauthor": "coauthor",
    "co-author": "coauthor",
    "editor": "editor",
    "coeditor": "coeditor",
    "co-editor": "coeditor",
    "translator": "translator",
    "foreword": "foreword",
    "introduction": "introduction",
}


def normalize_role(value: str | None, *, field_guarantees_authorship: bool = False) -> str:
    if not value:
        return "author" if field_guarantees_authorship else "unknown"
    return ROLE_MAP.get(value.strip().casefold(), "unknown")
