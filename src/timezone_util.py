from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

_FALLBACKS = (
    "Asia/Sakhalin",
    "Asia/Vladivostok",
    "Asia/Magadan",
)


def resolve_tz(name: str) -> timezone:
    """Resolve IANA zone; on Windows without tzdata fall back safely."""
    candidates = [name, *_FALLBACKS]
    seen = set()
    for key in candidates:
        if key in seen:
            continue
        seen.add(key)
        try:
            return ZoneInfo(key)
        except ZoneInfoNotFoundError:
            continue
        except Exception:  # noqa: BLE001
            continue
    logger.warning("timezone %s unavailable; using fixed UTC+11", name)
    return timezone(timedelta(hours=11))


def format_local(dt: datetime | None, tz_name: str) -> str:
    tz = resolve_tz(tz_name)
    when = dt or datetime.now(tz)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(tz).strftime("%d.%m.%Y %H:%M")
