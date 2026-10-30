from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from src.bot.admin_text import (
    ADMIN_HELP,
    format_exceptions_list,
    format_excluded_summary,
    format_pending_summary,
)
from src.bot.album import AlbumAggregator, AlbumBatch, extract_media
from src.config import Settings
from src.db import repository as repo
from src.db.session import session_scope
from src.services.caption import has_send_command
from src.services.claim_pipeline import ClaimPipeline
from src.services.exceptions_service import ExceptionsCache
from src.services.gmail_auth import GmailAuth, GmailAuthError
from src.services.jobs import BackgroundJobs
from src.services.sheets import SheetsRegistry

logger = logging.getLogger(__name__)

WIPE_CONFIRM = "CONFIRM"


def build_router(
    *,
    settings: Settings,
    pipeline: ClaimPipeline,
    gmail_auth: GmailAuth,
    jobs: BackgroundJobs,
    sheets: SheetsRegistry,
    exceptions_cache: ExceptionsCache,
) -> Router:
    router = Router()
    aggregator = AlbumAggregator(
        debounce_seconds=settings.album_debounce_seconds,
        on_ready=pipeline.handle_album,
    )

    @router.message(F.chat.id == settings.allowed_chat_id, F.photo | F.document)
    async def on_media(message: Message) -> None:
        # Albums: buffer all parts; /send checked on flush (usually on first caption).
        if message.media_group_id:
            if extract_media(message) is None:
                return
            await aggregator.push(message)
            return

        # /send on a reply/forward is intentional; only skip when command missing
        if not has_send_command(message):
            return
        if extract_media(message) is None:
            return
        await aggregator.push(message)

    def _caption_for_send_reply(replied: Message, send_message: Message) -> Message:
        args = (send_message.text or "").split(maxsplit=1)
        extra = args[1].strip() if len(args) > 1 else ""
        if extra:
            return replied.model_copy(
                update={"caption": f"/send {extra}", "caption_entities": None}
            )
        if has_send_command(replied):
            return replied
        caption = (replied.caption or "").strip()
        return replied.model_copy(
            update={"caption": f"/send {caption}".strip(), "caption_entities": None}
        )

    @router.message(Command("send"), F.chat.id == settings.allowed_chat_id)
    async def on_send_reply(message: Message) -> None:
        """ /send as reply to photo/document; albums use parts cached after flush. """
        replied = message.reply_to_message
        if replied is None:
            logger.info("send ignored: not a reply message_id=%s", message.message_id)
            return
        if extract_media(replied) is None:
            logger.info(
                "send ignored: reply has no photo/document message_id=%s",
                message.message_id,
            )
            return

        if replied.media_group_id:
            cached = aggregator.get_group(replied.chat.id, replied.media_group_id)
            if cached is not None:
                anchor = _caption_for_send_reply(cached.anchor, message)
                batch = AlbumBatch(
                    chat_id=cached.chat_id,
                    anchor=anchor,
                    messages=list(cached.messages),
                    media=list(cached.media),
                    media_group_id=cached.media_group_id,
                )
                await pipeline.handle_album(batch)
                return

        replied = _caption_for_send_reply(replied, message)
        media = extract_media(replied)
        if media is None:
            return
        batch = AlbumBatch(
            chat_id=replied.chat.id,
            anchor=replied,
            messages=[replied],
            media=[media],
            media_group_id=None,
        )
        await pipeline.handle_album(batch)

    def _is_admin(message: Message) -> bool:
        return (
            message.from_user is not None
            and message.from_user.id == settings.admin_telegram_id
        )

    @router.message(Command("help", "start"), F.chat.type == ChatType.PRIVATE)
    async def on_help(message: Message) -> None:
        if not _is_admin(message):
            return
        await message.answer(ADMIN_HELP)

    @router.message(Command("pending"), F.chat.type == ChatType.PRIVATE)
    async def on_pending(message: Message) -> None:
        if not _is_admin(message):
            return
        async with session_scope() as session:
            claims = await repo.list_not_entered(session)
            total = await repo.count_claims(session) if not claims else None
        await message.answer(
            format_pending_summary(
                claims, settings.timezone, total_claims=total
            )
        )

    @router.message(Command("excluded"), F.chat.type == ChatType.PRIVATE)
    async def on_excluded(message: Message) -> None:
        if not _is_admin(message):
            return
        async with session_scope() as session:
            claims = await repo.list_exception_claims(session)
        await message.answer(format_excluded_summary(claims, settings.timezone))

    @router.message(Command("alcohol"), F.chat.type == ChatType.PRIVATE)
    async def on_alcohol(message: Message) -> None:
        if not _is_admin(message):
            return
        args = (message.text or "").split(maxsplit=1)
        if len(args) < 2 or not args[1].strip().isdigit():
            await message.answer(
                "🍺 Пример: /alcohol 12\n"
                "Закрыть заявку как алкоголь (ЕГАИС). Id — в /pending"
            )
            return
        claim_id = int(args[1].strip())
        detail = await jobs.mark_alcohol(claim_id)
        await message.answer(detail)

    @router.message(Command("retry"), F.chat.type == ChatType.PRIVATE)
    async def on_retry(message: Message) -> None:
        if not _is_admin(message):
            return
        args = (message.text or "").split(maxsplit=1)
        if len(args) < 2 or not args[1].strip().isdigit():
            await message.answer(
                "🔁 Пример: /retry 12\n"
                "Все ошибки с файлами: /retry_errors\n"
                "Номера смотри в /pending"
            )
            return
        claim_id = int(args[1].strip())
        await message.answer(f"⏳ Retry #{claim_id}…")
        detail = await jobs.retry_error_claim(claim_id)
        await message.answer(detail)

    @router.message(Command("retry_errors"), F.chat.type == ChatType.PRIVATE)
    async def on_retry_errors(message: Message) -> None:
        if not _is_admin(message):
            return
        await message.answer("⏳ Retry всех ошибок…")
        detail = await jobs.retry_all_errors()
        # Telegram message limit
        if len(detail) > 4000:
            detail = detail[:3900] + "\n…(обрезано)"
        await message.answer(detail)

    @router.message(Command("exceptions"), F.chat.type == ChatType.PRIVATE)
    async def on_exceptions(message: Message) -> None:
        if not _is_admin(message):
            return
        try:
            items = await asyncio.to_thread(sheets.list_exceptions)
        except GmailAuthError as exc:
            await message.answer(f"❌ Sheets: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            await message.answer(f"❌ Не удалось прочитать исключения: {exc}")
            return
        exceptions_cache.set(items)
        await message.answer(format_exceptions_list(items))

    @router.message(Command("exception_add"), F.chat.type == ChatType.PRIVATE)
    async def on_exception_add(message: Message) -> None:
        if not _is_admin(message):
            return
        args = (message.text or "").split(maxsplit=1)
        if len(args) < 2 or not args[1].strip():
            await message.answer("➕ Пример: /exception_add ООО Ромашка")
            return
        name = args[1].strip()
        try:
            added = await asyncio.to_thread(sheets.add_exception, name)
        except GmailAuthError as exc:
            await message.answer(f"❌ Sheets: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            await message.answer(f"❌ Не удалось добавить: {exc}")
            return
        exceptions_cache.invalidate()
        if added:
            await message.answer(f"✅ Добавлено в исключения: {name}")
        else:
            await message.answer(f"ℹ️ Уже в списке: {name}")

    @router.message(Command("exception_del"), F.chat.type == ChatType.PRIVATE)
    async def on_exception_del(message: Message) -> None:
        if not _is_admin(message):
            return
        args = (message.text or "").split(maxsplit=1)
        if len(args) < 2 or not args[1].strip():
            await message.answer(
                "➖ Пример: /exception_del 2\nили /exception_del ООО Ромашка"
            )
            return
        query = args[1].strip()
        try:
            removed = await asyncio.to_thread(sheets.remove_exception, query)
        except GmailAuthError as exc:
            await message.answer(f"❌ Sheets: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            await message.answer(f"❌ Не удалось удалить: {exc}")
            return
        exceptions_cache.invalidate()
        if removed:
            await message.answer(f"✅ Удалено из исключений: {removed}")
        else:
            await message.answer(f"ℹ️ Не найдено: {query}")

    @router.message(Command("check_gmail"), F.chat.type == ChatType.PRIVATE)
    async def on_check_gmail(message: Message) -> None:
        if not _is_admin(message):
            return
        _ok, detail = await asyncio.to_thread(gmail_auth.check_gmail)
        await message.answer(detail)

    @router.message(Command("check_sheets"), F.chat.type == ChatType.PRIVATE)
    async def on_check_sheets(message: Message) -> None:
        if not _is_admin(message):
            return
        _ok, detail = await asyncio.to_thread(
            gmail_auth.check_sheets, settings.spreadsheet_id
        )
        await message.answer(detail)

    @router.message(Command("resync_sheets"), F.chat.type == ChatType.PRIVATE)
    async def on_resync_sheets(message: Message) -> None:
        if not _is_admin(message):
            return
        await message.answer("⏳ Пересобираю Sheets из БД…")
        try:
            detail = await jobs.resync_sheets()
        except Exception as exc:  # noqa: BLE001
            await message.answer(f"❌ Ошибка resync: {exc}")
            return
        await message.answer(detail)

    @router.message(Command("purge_errors"), F.chat.type == ChatType.PRIVATE)
    async def on_purge_errors(message: Message) -> None:
        if not _is_admin(message):
            return
        args = (message.text or "").split(maxsplit=1)
        if len(args) < 2 or args[1].strip() != WIPE_CONFIRM:
            await message.answer(
                "⚠️ Удалит из БД все заявки со статусом «Ошибка» и их папки "
                "вложений, затем пересоберёт реестр Sheets.\n"
                f"Для подтверждения: /purge_errors {WIPE_CONFIRM}"
            )
            return
        await message.answer("⏳ Удаляю ошибки и синхронизирую Sheets…")
        try:
            detail = await jobs.purge_errors()
        except Exception as exc:  # noqa: BLE001
            await message.answer(f"❌ Ошибка purge: {exc}")
            return
        await message.answer(detail)

    @router.message(Command("wipe_all"), F.chat.type == ChatType.PRIVATE)
    async def on_wipe_all(message: Message) -> None:
        if not _is_admin(message):
            return
        args = (message.text or "").split(maxsplit=1)
        if len(args) < 2 or args[1].strip() != WIPE_CONFIRM:
            await message.answer(
                "⚠️ Это удалит все заявки в БД, вложения и строки реестра Sheets.\n"
                f"Для подтверждения: /wipe_all {WIPE_CONFIRM}"
            )
            return
        await message.answer("⏳ Очищаю БД и Sheets…")
        try:
            detail = await jobs.wipe_all()
        except Exception as exc:  # noqa: BLE001
            await message.answer(f"❌ Ошибка wipe: {exc}")
            return
        await message.answer(detail)

    original_on_ready = aggregator._on_ready

    async def gated_on_ready(batch: AlbumBatch) -> None:
        if not any(has_send_command(m) for m in batch.messages):
            return
        for m in batch.messages:
            if has_send_command(m):
                batch.anchor = m
                break
        await original_on_ready(batch)

    aggregator._on_ready = gated_on_ready
    return router
