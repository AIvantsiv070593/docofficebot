from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from aiogram.types import Message

from src.services.media_types import MediaItem, guess_extension, is_allowed_media

logger = logging.getLogger(__name__)

AlbumHandler = Callable[["AlbumBatch"], Awaitable[None]]

# shortcut: Bot API cannot fetch other album parts; reply /send only works while cached
DEFAULT_RECENT_TTL_SECONDS = 3600.0


@dataclass
class AlbumBatch:
    chat_id: int
    anchor: Message
    messages: list[Message] = field(default_factory=list)
    media: list[MediaItem] = field(default_factory=list)
    media_group_id: str | None = None


@dataclass
class _CachedAlbum:
    batch: AlbumBatch
    saved_at: float


def extract_media(message: Message) -> MediaItem | None:
    if message.photo:
        photo = message.photo[-1]
        return MediaItem(
            file_id=photo.file_id,
            file_unique_id=photo.file_unique_id,
            file_name=f"{photo.file_unique_id}.jpg",
            mime_type="image/jpeg",
            kind="photo",
        )
    if message.document:
        doc = message.document
        name = doc.file_name or f"{doc.file_unique_id}"
        mime = doc.mime_type
        if not is_allowed_media(name, mime):
            return MediaItem(
                file_id=doc.file_id,
                file_unique_id=doc.file_unique_id,
                file_name=name,
                mime_type=mime,
                kind="unsupported",
            )
        ext = guess_extension(name, mime)
        if not name.casefold().endswith(ext):
            name = f"{name}{ext}"
        return MediaItem(
            file_id=doc.file_id,
            file_unique_id=doc.file_unique_id,
            file_name=name,
            mime_type=mime,
            kind="document",
        )
    return None


class AlbumAggregator:
    def __init__(
        self,
        debounce_seconds: float,
        on_ready: AlbumHandler,
        recent_ttl_seconds: float = DEFAULT_RECENT_TTL_SECONDS,
    ) -> None:
        self._debounce = debounce_seconds
        self._on_ready = on_ready
        self._recent_ttl = recent_ttl_seconds
        self._buffers: dict[str, AlbumBatch] = {}
        self._timers: dict[str, asyncio.Task[None]] = {}
        self._recent: dict[str, _CachedAlbum] = {}
        self._lock = asyncio.Lock()

    def get_group(self, chat_id: int, media_group_id: str) -> AlbumBatch | None:
        """Album parts cached after debounce flush (for /send reply)."""
        self._prune_recent()
        cached = self._recent.get(f"{chat_id}:{media_group_id}")
        return cached.batch if cached else None

    def _remember(self, batch: AlbumBatch) -> None:
        if not batch.media_group_id:
            return
        key = f"{batch.chat_id}:{batch.media_group_id}"
        self._recent[key] = _CachedAlbum(batch=batch, saved_at=time.monotonic())
        self._prune_recent()

    def _prune_recent(self) -> None:
        now = time.monotonic()
        expired = [
            key
            for key, item in self._recent.items()
            if now - item.saved_at > self._recent_ttl
        ]
        for key in expired:
            del self._recent[key]

    async def push(self, message: Message) -> None:
        media = extract_media(message)
        if media is None:
            return

        group_id = message.media_group_id
        key = (
            f"{message.chat.id}:{group_id}"
            if group_id
            else f"{message.chat.id}:single:{message.message_id}"
        )

        async with self._lock:
            batch = self._buffers.get(key)
            if batch is None:
                batch = AlbumBatch(
                    chat_id=message.chat.id,
                    anchor=message,
                    media_group_id=group_id,
                )
                self._buffers[key] = batch
            batch.messages.append(message)
            batch.media.append(media)
            if message.caption or (
                message.caption_entities and not batch.anchor.caption
            ):
                batch.anchor = message

            old = self._timers.get(key)
            if old and not old.done():
                old.cancel()
            self._timers[key] = asyncio.create_task(self._flush_later(key))

    async def _flush_later(self, key: str) -> None:
        try:
            await asyncio.sleep(self._debounce)
        except asyncio.CancelledError:
            return
        async with self._lock:
            batch = self._buffers.pop(key, None)
            self._timers.pop(key, None)
            if batch and batch.media_group_id:
                self._remember(batch)
        if batch:
            try:
                await self._on_ready(batch)
            except Exception:  # noqa: BLE001
                logger.exception("album handler failed key=%s", key)
