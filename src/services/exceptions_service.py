from __future__ import annotations

import re
import time

# Quotes / dashes / odd punct so «ООО "Гильдия"» matches «ООО Гильдия»
_PUNCT_RE = re.compile(r'["«»„“”\'`´‘’\-–—.,;:!?()\[\]{}]+')


def normalize_counterparty(value: str) -> str:
    text = _PUNCT_RE.sub(" ", value or "")
    return " ".join(text.casefold().split())


def is_exception(caption: str, exceptions: list[str]) -> bool:
    haystack = normalize_counterparty(caption)
    if not haystack:
        return False
    for item in exceptions:
        needle = normalize_counterparty(item)
        if needle and needle in haystack:
            return True
    return False


class ExceptionsCache:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._items: list[str] = []
        self._loaded_at = 0.0

    def get_if_fresh(self) -> list[str] | None:
        if time.monotonic() - self._loaded_at <= self._ttl:
            return list(self._items)
        return None

    def set(self, items: list[str]) -> None:
        self._items = list(items)
        self._loaded_at = time.monotonic()

    def invalidate(self) -> None:
        self._loaded_at = 0.0
