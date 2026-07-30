"""Content-addressed immutable raw-response cache."""

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CachedResponse:
    content_hash: str
    path: Path


class RawResponseCache:
    """Store source responses under their SHA-256 digest."""

    def __init__(self, root: Path = Path("data/cache")) -> None:
        self.root = root

    def store(self, source: str, content: bytes, suffix: str = ".json") -> CachedResponse:
        digest = hashlib.sha256(content).hexdigest()
        path = self.root / source / f"{digest}{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(content)
        return CachedResponse(content_hash=digest, path=path)
