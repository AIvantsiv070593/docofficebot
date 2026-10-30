from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.bot.reactions import set_status_reaction
from src.config import Settings
from src.db import repository as repo
from src.db.session import session_scope
from src.services.admin_alerts import AdminAlerter
from src.services.claim_pipeline import cleanup_claim_files
from src.services.gmail_auth import GmailAuthError
from src.services.gmail_sender import GmailSender
from src.services.sheets import SheetsRegistry
from src.statuses import ClaimStatus

logger = logging.getLogger(__name__)


def pick_send_paths(attachments_dir: str | Path) -> list[Path]:
    files = [p for p in sorted(Path(attachments_dir).glob("*")) if p.is_file()]
    double = [p for p in files if p.stem.endswith("_c_c")]
    single = [
        p for p in files if p.stem.endswith("_c") and not p.stem.endswith("_c_c")
    ]
    return double or single or files


class BackgroundJobs:
    def __init__(
        self,
        *,
        settings: Settings,
        gmail_sender: GmailSender,
        sheets: SheetsRegistry,
        alerter: AdminAlerter,
        bot,
    ) -> None:
        self._settings = settings
        self._gmail_sender = gmail_sender
        self._sheets = sheets
        self._alerter = alerter
        self._bot = bot

    async def resend_stale(self) -> None:
        older_than = datetime.now(timezone.utc) - timedelta(
            hours=self._settings.resend_after_hours
        )
        async with session_scope() as session:
            candidates = await repo.list_resend_candidates(
                session,
                older_than=older_than,
                max_attempts=self._settings.max_send_attempts,
            )
            exhausted = await repo.list_sent_without_appeal(session)
            claim_ids = [c.id for c in candidates]
            exhausted_ids = [
                c.id
                for c in exhausted
                if c.resend_count >= self._settings.max_send_attempts
                and c.last_sent_at is not None
                and c.last_sent_at <= older_than
            ]

        for claim_id in claim_ids:
            await self._resend_one(claim_id)
        for claim_id in exhausted_ids:
            async with session_scope() as session:
                claim = await repo.get_claim_by_id(session, claim_id)
                if not claim:
                    continue
                chat_id, message_id = claim.chat_id, claim.message_id
            await self._mark_no_reply(claim_id, chat_id, message_id, reason=None)

    async def _resend_one(self, claim_id: int) -> None:
        async with session_scope() as session:
            claim = await repo.get_claim_by_id(session, claim_id)
            if not claim or claim.status != ClaimStatus.SENT.value:
                return
            attachments_dir = claim.attachments_dir
            subject = claim.outgoing_subject
            resend_count = claim.resend_count
            chat_id = claim.chat_id
            message_id = claim.message_id

        if resend_count >= self._settings.max_send_attempts:
            await self._mark_no_reply(claim_id, chat_id, message_id, reason=None)
            return

        if not attachments_dir or not Path(attachments_dir).exists():
            await self._mark_no_reply(
                claim_id,
                chat_id,
                message_id,
                reason="нет файлов для повтора",
            )
            return

        send_paths = pick_send_paths(attachments_dir)
        if not send_paths:
            await self._mark_no_reply(
                claim_id,
                chat_id,
                message_id,
                reason="нет файлов для повтора",
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
                text=f"Gmail auth on resend claim={claim_id}: {exc}",
                cooldown_seconds=self._settings.gmail_auth_alert_cooldown_seconds,
            )
            return
        except Exception as exc:  # noqa: BLE001
            await self._alerter.send(
                alert_key=f"resend_fail:{claim_id}",
                text=f"Resend failed claim={claim_id}: {exc}",
            )
            return

        async with session_scope() as session:
            claim = await repo.get_claim_by_id(session, claim_id)
            if not claim:
                return
            await repo.update_claim_fields(
                session,
                claim,
                gmail_message_id=gmail_id,
                gmail_thread_id=thread_id,
                gmail_rfc_message_id=rfc_id,
                last_sent_at=datetime.now(timezone.utc),
                resend_count=resend_count + 1,
            )

    async def retry_error_claim(self, claim_id: int) -> str:
        """Re-send an ERROR claim from saved attachments (after Gmail auth fix)."""
        async with session_scope() as session:
            claim = await repo.get_claim_by_id(session, claim_id)
            if not claim:
                return f"❌ #{claim_id}: не найдена"
            if claim.status != ClaimStatus.ERROR.value:
                return f"❌ #{claim_id}: статус «{claim.status}», нужен «Ошибка»"
            attachments_dir = claim.attachments_dir
            subject = claim.outgoing_subject
            chat_id = claim.chat_id
            message_id = claim.message_id
            caption = (claim.caption or "").strip() or "—"

        if not attachments_dir or not Path(attachments_dir).exists():
            return (
                f"❌ #{claim_id}: нет файлов на диске.\n"
                f"📎 {caption}\n"
                "Сделай реплай /send на исходное сообщение в чате."
            )
        send_paths = pick_send_paths(attachments_dir)
        if not send_paths:
            return (
                f"❌ #{claim_id}: папка вложений пуста.\n"
                "Сделай реплай /send на исходное сообщение в чате."
            )

        try:
            gmail_id, thread_id, rfc_id = self._gmail_sender.send(
                to=self._settings.invoice_to_email,
                subject=subject,
                body=self._settings.mail_body,
                attachments=send_paths,
            )
        except GmailAuthError as exc:
            return f"❌ #{claim_id}: Gmail auth — {exc}"
        except Exception as exc:  # noqa: BLE001
            return f"❌ #{claim_id}: отправка не удалась — {exc}"

        now = datetime.now(timezone.utc)
        async with session_scope() as session:
            claim = await repo.get_claim_by_id(session, claim_id)
            if not claim:
                return f"❌ #{claim_id}: исчезла после отправки"
            await repo.update_claim_fields(
                session,
                claim,
                status=ClaimStatus.SENT.value,
                error_text=None,
                gmail_message_id=gmail_id,
                gmail_thread_id=thread_id,
                gmail_rfc_message_id=rfc_id,
                last_sent_at=now,
                resend_count=max(claim.resend_count, 1),
            )

        await set_status_reaction(
            self._bot,
            chat_id=chat_id,
            message_id=message_id,
            status=ClaimStatus.SENT,
        )
        try:
            async with session_scope() as session:
                claim = await repo.get_claim_by_id(session, claim_id)
                if claim:
                    row = self._sheets.upsert_claim_row(claim)
                    await repo.mark_sheet_synced(
                        session, claim_id, row or claim.sheet_row or 0
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("sheets sync after retry failed claim=%s: %s", claim_id, exc)

        return f"✅ #{claim_id} переотправлено → ⚡\n📎 {caption}"

    async def retry_all_errors(self) -> str:
        async with session_scope() as session:
            claims = await repo.list_error_claims(session)
            ids = [c.id for c in claims]
        if not ids:
            return "ℹ️ Заявок в статусе «Ошибка» нет."
        lines = [f"🔁 Retry ошибок: {len(ids)}"]
        for claim_id in ids:
            lines.append(await self.retry_error_claim(claim_id))
        return "\n\n".join(lines)

    async def mark_alcohol(self, claim_id: int) -> str:
        """Manually close a claim as alcohol (EGAIS) — for old unmatched replies."""
        allowed = {
            ClaimStatus.ACCEPTED.value,
            ClaimStatus.SENT.value,
            ClaimStatus.RECEIVED.value,
            ClaimStatus.ERROR.value,
            ClaimStatus.NO_REPLY.value,
        }
        async with session_scope() as session:
            claim = await repo.get_claim_by_id(session, claim_id)
            if not claim:
                return f"❌ #{claim_id}: не найдена"
            if claim.status == ClaimStatus.ALCOHOL.value:
                return f"ℹ️ #{claim_id}: уже «Алкоголь»"
            if claim.status not in allowed:
                return (
                    f"❌ #{claim_id}: статус «{claim.status}», "
                    "можно только из работы/ошибки"
                )
            attachments_dir = claim.attachments_dir
            chat_id = claim.chat_id
            message_id = claim.message_id
            caption = (claim.caption or "").strip() or "—"
            await repo.update_claim_fields(
                session,
                claim,
                status=ClaimStatus.ALCOHOL.value,
                error_text=None,
            )

        await set_status_reaction(
            self._bot,
            chat_id=chat_id,
            message_id=message_id,
            status=ClaimStatus.ALCOHOL,
        )
        cleanup_claim_files(attachments_dir)
        try:
            async with session_scope() as session:
                claim = await repo.get_claim_by_id(session, claim_id)
                if claim:
                    row = self._sheets.upsert_claim_row(claim)
                    await repo.mark_sheet_synced(
                        session, claim_id, row or claim.sheet_row or 0
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "sheets sync after alcohol mark failed claim=%s: %s", claim_id, exc
            )
        return f"🍺 #{claim_id} → Алкоголь\n📎 {caption}"

    async def _mark_no_reply(
        self,
        claim_id: int,
        chat_id: int,
        message_id: int,
        *,
        reason: str | None,
    ) -> None:
        error = reason or "нет ответа DocsInBox после 3 попыток"
        attachments_dir = None
        async with session_scope() as session:
            claim = await repo.get_claim_by_id(session, claim_id)
            if not claim:
                return
            attachments_dir = claim.attachments_dir
            await repo.update_claim_fields(
                session,
                claim,
                status=ClaimStatus.NO_REPLY.value,
                error_text=error,
            )
        await set_status_reaction(
            self._bot,
            chat_id=chat_id,
            message_id=message_id,
            status=ClaimStatus.NO_REPLY,
        )
        cleanup_claim_files(attachments_dir)
        await self._alerter.send(
            alert_key=f"no_reply:{claim_id}",
            text=f"Нет ответа claim={claim_id} error={error}",
        )
        try:
            async with session_scope() as session:
                claim = await repo.get_claim_by_id(session, claim_id)
                if claim:
                    row = self._sheets.upsert_claim_row(claim)
                    await repo.mark_sheet_synced(
                        session, claim_id, row or claim.sheet_row or 0
                    )
        except Exception as exc:  # noqa: BLE001
            await self._alerter.send(
                alert_key=f"sheets_sync:{claim_id}",
                text=f"Sheets sync failed claim_id={claim_id}: {exc}",
            )

    async def sync_dirty_sheets(self) -> int:
        synced = 0
        while True:
            async with session_scope() as session:
                dirty = await repo.list_dirty_claims(session, limit=100)
                ids = [c.id for c in dirty]
            if not ids:
                return synced
            progress = 0
            for claim_id in ids:
                try:
                    async with session_scope() as session:
                        claim = await repo.get_claim_by_id(session, claim_id)
                        if not claim:
                            continue
                        row = self._sheets.upsert_claim_row(claim)
                        await repo.mark_sheet_synced(
                            session, claim_id, row or claim.sheet_row or 0
                        )
                        synced += 1
                        progress += 1
                except Exception as exc:  # noqa: BLE001
                    await self._alerter.send(
                        alert_key=f"sheets_sync:{claim_id}",
                        text=f"Sheets dirty sync failed claim={claim_id}: {exc}",
                    )
            if progress == 0:
                return synced

    async def resync_sheets(self) -> str:
        await asyncio.to_thread(self._sheets.clear_registry)
        async with session_scope() as session:
            total = await repo.mark_all_for_sheet_resync(session)
        synced = await self.sync_dirty_sheets()
        return (
            f"✅ Sheets пересобран из БД: заявок {total}, записано {synced}"
        )

    async def wipe_all(self) -> str:
        await asyncio.to_thread(self._sheets.clear_registry)
        async with session_scope() as session:
            counts = await repo.wipe_operational_data(session)
        claims_root = self._settings.claims_dir
        if claims_root.exists():
            shutil.rmtree(claims_root, ignore_errors=True)
        claims_root.mkdir(parents=True, exist_ok=True)
        return (
            "✅ Очищены БД и Sheets (реестр).\n"
            f"🗂 claims={counts['claims']}, "
            f"✉️ emails={counts['processed_emails']}, "
            f"❓ unmatched={counts['unmatched_emails']}"
        )

    async def purge_errors(self) -> str:
        """Delete all ERROR claims + their attachment folders, then rebuild Sheets."""
        async with session_scope() as session:
            ids = await repo.delete_error_claims(session)
        for claim_id in ids:
            cleanup_claim_files(str(self._settings.claims_dir / str(claim_id)))
        if not ids:
            return "ℹ️ Заявок со статусом «Ошибка» не было."
        ids_preview = ", ".join(f"#{i}" for i in ids[:20])
        if len(ids) > 20:
            ids_preview += f" … (+{len(ids) - 20})"
        resync = await self.resync_sheets()
        return (
            f"✅ Удалено ошибок: {len(ids)} ({ids_preview})\n"
            f"{resync}"
        )

    async def cleanup_orphan_claims(self) -> None:
        # Keep ERROR folders — /retry needs them. Drop only terminal done/no-retry.
        purge = {
            ClaimStatus.EXCEPTION.value,
            ClaimStatus.ENTERED.value,
            ClaimStatus.ALCOHOL.value,
            ClaimStatus.NO_REPLY.value,
        }
        claims_root = self._settings.claims_dir
        if not claims_root.exists():
            return
        async with session_scope() as session:
            for path in claims_root.iterdir():
                if not path.is_dir() or not path.name.isdigit():
                    continue
                claim_id = int(path.name)
                claim = await repo.get_claim_by_id(session, claim_id)
                if claim is None or claim.status in purge:
                    shutil.rmtree(path, ignore_errors=True)

    async def health_check(self) -> None:
        # Do not call AdminAlerter inside this txn (nested SQLite session → locked).
        stale_age: timedelta | None = None
        async with session_scope() as session:
            await repo.touch_heartbeat(session, "main")
            hb = await repo.get_heartbeat(session, "gmail_poll")
            if hb is None:
                return
            age = datetime.now(timezone.utc) - hb.updated_at.replace(tzinfo=timezone.utc)
            if age > timedelta(minutes=self._settings.health_stale_minutes):
                stale_age = age
        if stale_age is not None:
            await self._alerter.send(
                alert_key="health_stale",
                text=(
                    f"Health: gmail_poll stale for {stale_age}. "
                    "Бот возможно завис — проверь контейнер."
                ),
                cooldown_seconds=3600,
            )
