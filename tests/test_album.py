from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from src.bot.album import AlbumAggregator, AlbumBatch


def _photo_msg(
    *,
    chat_id: int,
    message_id: int,
    group_id: str,
    file_unique_id: str,
    caption: str | None = None,
) -> MagicMock:
    m = MagicMock()
    m.chat.id = chat_id
    m.message_id = message_id
    m.media_group_id = group_id
    m.caption = caption
    m.caption_entities = None
    m.photo = [MagicMock(file_id=f"id-{file_unique_id}", file_unique_id=file_unique_id)]
    m.document = None
    return m


@pytest.mark.asyncio
async def test_flush_remembers_album_for_reply():
    seen: list[AlbumBatch] = []

    async def on_ready(batch: AlbumBatch) -> None:
        seen.append(batch)

    agg = AlbumAggregator(debounce_seconds=0.05, on_ready=on_ready)
    m1 = _photo_msg(chat_id=10, message_id=1, group_id="g1", file_unique_id="ua")
    m2 = _photo_msg(
        chat_id=10,
        message_id=2,
        group_id="g1",
        file_unique_id="ub",
        caption="ИП Тест №1",
    )

    await agg.push(m1)
    await agg.push(m2)
    await asyncio.sleep(0.12)

    assert len(seen) == 1
    assert len(seen[0].media) == 2
    cached = agg.get_group(10, "g1")
    assert cached is not None
    assert len(cached.media) == 2
    assert cached.anchor is m2


def test_get_group_expires():
    async def noop(_batch: AlbumBatch) -> None:
        return None

    agg = AlbumAggregator(
        debounce_seconds=1.0, on_ready=noop, recent_ttl_seconds=0.01
    )
    batch = AlbumBatch(chat_id=1, anchor=MagicMock(), media_group_id="old")
    agg._remember(batch)
    time.sleep(0.02)
    assert agg.get_group(1, "old") is None
