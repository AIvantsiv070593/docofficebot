from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot

from src.services.media_types import MediaItem

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT_SECONDS = 120
DOWNLOAD_ATTEMPTS = 3


async def download_media_items(
    bot: Bot, items: list[MediaItem], target_dir: Path
) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, item in enumerate(items):
        dest = target_dir / f"{index:02d}_{item.file_name}"
        await _download_one(bot, item.file_id, dest)
        paths.append(dest)
    return paths


async def _download_one(bot: Bot, file_id: str, dest: Path) -> None:
    last_exc: BaseException | None = None
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            await bot.download(
                file_id, destination=dest, timeout=DOWNLOAD_TIMEOUT_SECONDS
            )
            if not dest.exists() or dest.stat().st_size <= 0:
                raise RuntimeError(f"empty download: {dest.name}")
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(
                "download attempt %s/%s failed file=%s err=%s: %s",
                attempt,
                DOWNLOAD_ATTEMPTS,
                dest.name,
                type(exc).__name__,
                exc,
            )
            if dest.exists():
                dest.unlink(missing_ok=True)
            if attempt < DOWNLOAD_ATTEMPTS:
                await asyncio.sleep(attempt)
    assert last_exc is not None
    raise RuntimeError(
        f"{type(last_exc).__name__}: {last_exc or 'timeout/network'}"
    ) from last_exc
