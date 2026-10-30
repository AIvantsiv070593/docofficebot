from __future__ import annotations

from dataclasses import dataclass

ALLOWED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".heic", ".heif"})
ALLOWED_MIME_PREFIXES = (
    "image/jpeg",
    "image/png",
    "image/heic",
    "image/heif",
)


@dataclass(frozen=True)
class MediaItem:
    file_id: str
    file_unique_id: str
    file_name: str
    mime_type: str | None
    kind: str  # photo | document


def is_allowed_media(file_name: str, mime_type: str | None) -> bool:
    name = (file_name or "").casefold()
    if any(name.endswith(ext) for ext in ALLOWED_EXTENSIONS):
        return True
    mime = (mime_type or "").casefold()
    return any(mime.startswith(prefix) for prefix in ALLOWED_MIME_PREFIXES)


def guess_extension(file_name: str, mime_type: str | None) -> str:
    name = (file_name or "").casefold()
    for ext in ALLOWED_EXTENSIONS:
        if name.endswith(ext):
            return ext
    mime = (mime_type or "").casefold()
    if mime.startswith("image/png"):
        return ".png"
    if mime.startswith("image/heic") or mime.startswith("image/heif"):
        return ".heic"
    return ".jpg"
