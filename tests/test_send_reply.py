"""Regression: explicit /send must not be dropped for reply/forward media."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.album import AlbumBatch, extract_media
from src.services.caption import has_send_command
from src.services.claim_pipeline import ClaimPipeline


def _photo(*, caption: str | None = None, reply: bool = False, forwarded: bool = False):
    m = MagicMock()
    m.chat.id = -100
    m.message_id = 7
    m.media_group_id = None
    m.caption = caption
    m.text = None
    m.caption_entities = None
    m.entities = None
    m.photo = [MagicMock(file_id="f", file_unique_id="u")]
    m.document = None
    m.reply_to_message = MagicMock() if reply else None
    m.forward_origin = MagicMock() if forwarded else None
    m.forward_date = None
    return m


def test_send_on_reply_photo_is_detected():
    msg = _photo(caption="/send ИП Тест №1", reply=True)
    assert has_send_command(msg)
    assert extract_media(msg) is not None


@pytest.mark.asyncio
async def test_pipeline_accepts_reply_and_forward_with_send():
    settings = SimpleNamespace(
        allowed_chat_id=-100,
        mail_subject_prefix="PREFIX",
        max_attachment_bytes=10_000_000,
        claims_dir=MagicMock(),
    )
    pipeline = ClaimPipeline(
        bot=AsyncMock(),
        settings=settings,
        sheets=MagicMock(),
        exceptions_cache=MagicMock(),
        gmail_sender=MagicMock(),
        alerter=AsyncMock(),
        gmail_auth_ok=lambda: False,
    )
    anchor = _photo(caption="/send ИП Тест №1", reply=True, forwarded=True)
    batch = AlbumBatch(
        chat_id=-100,
        anchor=anchor,
        messages=[anchor],
        media=[extract_media(anchor)],
        media_group_id=None,
    )

    with (
        patch("src.services.claim_pipeline.session_scope") as scope,
        patch("src.services.claim_pipeline.repo") as repo_mock,
        patch("src.services.claim_pipeline.set_status_reaction", new_callable=AsyncMock),
    ):
        session = AsyncMock()
        scope.return_value.__aenter__ = AsyncMock(return_value=session)
        scope.return_value.__aexit__ = AsyncMock(return_value=None)
        repo_mock.find_active_by_dedupe = AsyncMock(return_value=None)
        claim = MagicMock(id=1)
        repo_mock.create_claim = AsyncMock(return_value=claim)
        pipeline._sync_sheet = AsyncMock()
        pipeline._fail = AsyncMock()

        await pipeline.handle_album(batch)

        repo_mock.create_claim.assert_awaited()
        assert pipeline._fail.call_args.kwargs.get("stage") == "gmail_auth"
