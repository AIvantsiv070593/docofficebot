from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Callable
from pathlib import Path

from aiogram import Bot

from src.bot.album import AlbumBatch
from src.bot.reactions import set_status_reaction
from src.config import Settings
from src.db import repository as repo
from src.db.session import session_scope
from src.parsers.docsinbox import normalize_subject
from src.services.admin_alerts import AdminAlerter
from src.services.caption import (
    build_outgoing_subject,
    clean_claim_caption,
    extract_caption,
)
from src.services.compress import compress_attachments_to_limit, total_size
from src.services.download import download_media_items
from src.services.exceptions_service import ExceptionsCache, is_exception
from src.services.gmail_auth import GmailAuthError
from src.services.gmail_sender import GmailSender
from src.services.sheets import SheetsRegistry
from src.statuses import ClaimStatus

logger = logging.getLogger(__name__)


class ClaimPipeline:
    def __init__(
        self,
        *,
        bot: Bot,
        settings: Settings,
        sheets: SheetsRegistry,
        exceptions_cache: ExceptionsCache,
        gmail_sender: GmailSender,
        alerter: AdminAlerter,
        gmail_auth_ok: Callable[[], bool],
    ) -> None:
        self._bot = bot
        self._settings = settings
        self._sheets = sheets
        self._exceptions_cache = exceptions_cache
        self._gmail_sender = gmail_sender
        self._alerter = alerter
        self._gmail_auth_ok = gmail_auth_ok

    async def handle_album(self, batch: AlbumBatch) -> None:
        anchor = batch.anchor
        # reply/forward ok: caller already required explicit /send
        if batch.chat_id != self._settings.allowed_chat_id:
            return

        caption_raw = extract_caption(anchor)
        caption_clean = clean_claim_caption(caption_raw)
        subject = normalize_subject(
            build_outgoing_subject(self._settings.mail_subject_prefix, caption_clean)
        )
        dedupe_key = (
            f"mg:{batch.media_group_id}"
            if batch.media_group_id
            else f"msg:{anchor.message_id}"
        )

        async with session_scope() as session:
            existing = await repo.find_by_dedupe(session, batch.chat_id, dedupe_key)
            if existing and existing.status in {
                ClaimStatus.ACCEPTED.value,
                ClaimStatus.SENT.value,
                ClaimStatus.RECEIVED.value,
            }:
                logger.info("duplicate album skipped", extra={"claim_id": existing.id})
                return
            if existing and existing.status != ClaimStatus.ERROR.value:
                # ENTERED / EXCEPTION / NO_REPLY — не переоткрываем
                logger.info(
                    "final claim skipped retry",
                    extra={"claim_id": existing.id, "status": existing.status},
                )
                return

            retry_from = None
            if existing and existing.status == ClaimStatus.ERROR.value:
                retry_from = existing
            elif existing is None:
                # New Telegram message, same invoice text as an ERROR → fix old row
                retry_from = await repo.find_error_by_outgoing_subject(
                    session, batch.chat_id, subject
                )

            if retry_from is not None:
                claim = await repo.update_claim_fields(
                    session,
                    retry_from,
                    message_id=anchor.message_id,
                    media_group_id=batch.media_group_id,
                    dedupe_key=dedupe_key,
                    caption=caption_clean,
                    outgoing_subject=subject,
                    file_count=len(batch.media),
                    status=ClaimStatus.ACCEPTED.value,
                    error_text=None,
                    attachments_dir=None,
                    attachments_compressed=False,
                    gmail_message_id=None,
                    gmail_thread_id=None,
                    gmail_rfc_message_id=None,
                    resend_count=0,
                    last_sent_at=None,
                )
                claim_id = claim.id
            else:
                claim = await repo.create_claim(
                    session,
                    chat_id=batch.chat_id,
                    message_id=anchor.message_id,
                    media_group_id=batch.media_group_id,
                    dedupe_key=dedupe_key,
                    caption=caption_clean,
                    outgoing_subject=subject,
                    file_count=len(batch.media),
                    status=ClaimStatus.ACCEPTED,
                )
                claim_id = claim.id

        await set_status_reaction(
            self._bot,
            chat_id=batch.chat_id,
            message_id=anchor.message_id,
            status=ClaimStatus.ACCEPTED,
        )
        await self._sync_sheet(claim_id)

        if len(caption_clean) < 3:
            await self._fail(
                claim_id,
                batch,
                error="нет подписи",
                stage="caption",
            )
            return

        if any(item.kind == "unsupported" for item in batch.media):
            bad = [i for i in batch.media if i.kind == "unsupported"]
            await self._fail(
                claim_id,
                batch,
                error="неподдерживаемый тип файла",
                stage="media_type",
                extra=f"{bad[0].file_name} mime={bad[0].mime_type}",
            )
            return

        exceptions = await self._load_exceptions()
        if is_exception(caption_clean, exceptions):
            async with session_scope() as session:
                claim = await repo.get_claim_by_id(session, claim_id)
                if claim:
                    await repo.update_claim_fields(
                        session, claim, status=ClaimStatus.EXCEPTION.value, error_text=None
                    )
            await set_status_reaction(
                self._bot,
                chat_id=batch.chat_id,
                message_id=anchor.message_id,
                status=ClaimStatus.EXCEPTION,
            )
            await self._sync_sheet(claim_id)
            return

        # Download before Gmail check so ERROR leaves files for /retry
        claim_dir = self._settings.claims_dir / str(claim_id)
        if claim_dir.exists():
            shutil.rmtree(claim_dir, ignore_errors=True)
        try:
            paths = await download_media_items(self._bot, batch.media, claim_dir)
        except Exception as exc:  # noqa: BLE001
            await self._fail(
                claim_id,
                batch,
                error="не удалось скачать",
                stage="download",
                extra=f"{type(exc).__name__}: {exc}",
            )
            return

        try:
            send_paths, compressed = compress_attachments_to_limit(
                paths, self._settings.max_attachment_bytes
            )
            if total_size(send_paths) > self._settings.max_attachment_bytes:
                await self._fail(
                    claim_id,
                    batch,
                    error="слишком большой объём",
                    stage="compress",
                )
                return
        except Exception as exc:  # noqa: BLE001
            await self._fail(
                claim_id,
                batch,
                error="ошибка сжатия",
                stage="compress",
                extra=str(exc),
            )
            return

        async with session_scope() as session:
            claim = await repo.get_claim_by_id(session, claim_id)
            if claim:
                await repo.update_claim_fields(
                    session,
                    claim,
                    attachments_dir=str(claim_dir),
                    attachments_compressed=compressed,
                )

        if not self._gmail_auth_ok():
            await self._fail(
                claim_id,
                batch,
                error="Gmail auth",
                stage="gmail_auth",
            )
            return

        try:
            gmail_id, thread_id, rfc_id = self._gmail_sender.send(
                to=self._settings.invoice_to_email,
                subject=subject,
                body=self._settings.mail_body,
                attachments=send_paths,
            )
        except GmailAuthError as exc:
            await self._alerter.send(
                alert_key="gmail_auth",
                text=(
                    f"Gmail: нужна переавторизация {self._settings.gmail_user}. "
                    f"См. README. detail={exc}"
                ),
                cooldown_seconds=self._settings.gmail_auth_alert_cooldown_seconds,
            )
            await self._fail(
                claim_id,
                batch,
                error="Gmail auth",
                stage="gmail_send",
                extra=str(exc),
            )
            return
        except Exception as exc:  # noqa: BLE001
            await self._fail(
                claim_id,
                batch,
                error="ошибка отправки Gmail",
                stage="gmail_send",
                extra=str(exc),
            )
            return

        from datetime import datetime, timezone

        async with session_scope() as session:
            claim = await repo.get_claim_by_id(session, claim_id)
            if claim:
                await repo.update_claim_fields(
                    session,
                    claim,
                    status=ClaimStatus.SENT.value,
                    gmail_message_id=gmail_id,
                    gmail_thread_id=thread_id,
                    gmail_rfc_message_id=rfc_id,
                    last_sent_at=datetime.now(timezone.utc),
                    resend_count=1,
                    error_text=None,
                )

        await set_status_reaction(
            self._bot,
            chat_id=batch.chat_id,
            message_id=anchor.message_id,
            status=ClaimStatus.SENT,
        )
        await self._sync_sheet(claim_id)

    async def _load_exceptions(self) -> list[str]:
        cached = self._exceptions_cache.get_if_fresh()
        if cached is not None:
            return cached
        try:
            items = self._sheets.list_exceptions()
            self._exceptions_cache.set(items)
            return items
        except Exception as exc:  # noqa: BLE001
            await self._alerter.send(
                alert_key="sheets_exceptions",
                text=f"Sheets exceptions read failed: {exc}",
            )
            return cached or []

    async def _sync_sheet(self, claim_id: int) -> None:
        try:
            async with session_scope() as session:
                claim = await repo.get_claim_by_id(session, claim_id)
                if not claim:
                    return
                row = self._sheets.upsert_claim_row(claim)
                await repo.mark_sheet_synced(session, claim_id, row or claim.sheet_row or 0)
        except Exception as exc:  # noqa: BLE001
            await self._alerter.send(
                alert_key=f"sheets_sync:{claim_id}",
                text=f"Sheets sync failed claim_id={claim_id}: {exc}",
            )

    async def _fail(
        self,
        claim_id: int,
        batch: AlbumBatch,
        *,
        error: str,
        stage: str,
        extra: str = "",
    ) -> None:
        async with session_scope() as session:
            claim = await repo.get_claim_by_id(session, claim_id)
            if claim:
                await repo.update_claim_fields(
                    session,
                    claim,
                    status=ClaimStatus.ERROR.value,
                    error_text=error,
                )
                subject = claim.outgoing_subject
            else:
                subject = ""
        await set_status_reaction(
            self._bot,
            chat_id=batch.chat_id,
            message_id=batch.anchor.message_id,
            status=ClaimStatus.ERROR,
        )
        await self._sync_sheet(claim_id)
        await self._alerter.send(
            alert_key=f"fail:{claim_id}:{stage}",
            text=(
                f"Ошибка заявки #{claim_id}\n"
                f"stage={stage}\n"
                f"error={error}\n"
                f"extra={extra}\n"
                f"subject={subject}\n"
                f"chat_id={batch.chat_id} message_id={batch.anchor.message_id}"
            ),
        )


def cleanup_claim_files(attachments_dir: str | None) -> None:
    if not attachments_dir:
        return
    path = Path(attachments_dir)
    if path.exists() and path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def docs_to_json(documents: list) -> str:
    payload = [
        {
            "sp_number": d.sp_number,
            "date": d.date,
            "url": d.url,
            "dxbx_id": d.dxbx_id,
        }
        for d in documents
    ]
    return json.dumps(payload, ensure_ascii=False)
