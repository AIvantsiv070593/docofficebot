from __future__ import annotations

import base64
import json
import logging
from email.utils import parseaddr

from src.bot.reactions import set_status_reaction
from src.config import Settings
from src.db import repository as repo
from src.db.session import session_scope
from src.parsers.docsinbox import IncomingKind, parse_incoming_email
from src.services.admin_alerts import AdminAlerter
from src.services.claim_pipeline import cleanup_claim_files, docs_to_json
from src.services.gmail_auth import GmailAuth, GmailAuthError
from src.services.matching import match_appeal_email, match_entered_email
from src.services.sheets import SheetsRegistry
from src.statuses import ClaimStatus

logger = logging.getLogger(__name__)


class GmailPoller:
    def __init__(
        self,
        *,
        auth: GmailAuth,
        settings: Settings,
        sheets: SheetsRegistry,
        alerter: AdminAlerter,
        bot,
    ) -> None:
        self._auth = auth
        self._settings = settings
        self._sheets = sheets
        self._alerter = alerter
        self._bot = bot

    async def poll_once(self) -> None:
        try:
            service = self._auth.build_service()
        except GmailAuthError as exc:
            await self._alerter.send(
                alert_key="gmail_auth",
                text=(
                    f"Gmail: нужна переавторизация {self._settings.gmail_user}. "
                    f"См. README. detail={exc}"
                ),
                cooldown_seconds=self._settings.gmail_auth_alert_cooldown_seconds,
            )
            return

        query = f"from:{self._settings.invoice_to_email} newer_than:14d"
        try:
            listed = (
                service.users()
                .messages()
                .list(userId="me", q=query, maxResults=50)
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            await self._alerter.send(
                alert_key="gmail_poll",
                text=f"Gmail poll list failed: {exc}",
            )
            return

        for item in listed.get("messages", []):
            gmail_id = item["id"]
            async with session_scope() as session:
                if await repo.is_email_processed(session, gmail_id):
                    continue
            try:
                raw = (
                    service.users()
                    .messages()
                    .get(userId="me", id=gmail_id, format="full")
                    .execute()
                )
                await self._handle_message(raw)
            except Exception as exc:  # noqa: BLE001
                logger.exception("handle gmail message failed id=%s", gmail_id)
                await self._alerter.send(
                    alert_key=f"gmail_handle:{gmail_id}",
                    text=f"Gmail handle failed id={gmail_id}: {exc}",
                )

        async with session_scope() as session:
            await repo.touch_heartbeat(session, "gmail_poll")

    async def _handle_message(self, raw: dict) -> None:
        gmail_id = raw["id"]
        thread_id = raw.get("threadId")
        payload = raw.get("payload", {})
        headers = {
            h["name"].lower(): h["value"] for h in payload.get("headers", [])
        }
        subject = headers.get("subject", "")
        from_addr = parseaddr(headers.get("from", ""))[1]
        in_reply_to = headers.get("in-reply-to")
        references = headers.get("references")
        body = _extract_body(payload)
        snippet = raw.get("snippet", "")[:500]
        parsed = parse_incoming_email(subject=subject, body=body)

        # Do not call AdminAlerter inside this write txn: it opens its own
        # session and SQLite then raises "database is locked".
        pending_alert: tuple[str, str] | None = None
        claim_id: int | None = None
        chat_id: int | None = None
        message_id: int | None = None
        attachments_dir: str | None = None
        matched_kind: IncomingKind | None = None

        async with session_scope() as session:
            if not await repo.mark_email_processed(
                session, gmail_id, kind=parsed.kind.value, claim_id=None
            ):
                return

            if parsed.kind == IncomingKind.APPEAL:
                match = await match_appeal_email(
                    session,
                    subject=subject,
                    thread_id=thread_id,
                    in_reply_to=in_reply_to,
                    references=references,
                )
                if not match.claim or not parsed.appeal_number:
                    await repo.add_unmatched(
                        session,
                        gmail_id=gmail_id,
                        from_addr=from_addr,
                        subject=subject,
                        snippet=snippet,
                        reason=match.reason,
                    )
                    pending_alert = (
                        f"unmatched:{gmail_id}",
                        (
                            f"Unmatched DocsInBox appeal\n"
                            f"gmail_id={gmail_id}\nfrom={from_addr}\n"
                            f"subject={subject}\nreason={match.reason}\n"
                            f"snippet={snippet}"
                        ),
                    )
                else:
                    claim = match.claim
                    if (
                        claim.appeal_number
                        and claim.appeal_number != parsed.appeal_number
                    ):
                        await repo.add_unmatched(
                            session,
                            gmail_id=gmail_id,
                            from_addr=from_addr,
                            subject=subject,
                            snippet=snippet,
                            reason="appeal_conflict",
                        )
                        pending_alert = (
                            f"appeal_conflict:{claim.id}",
                            (
                                f"Appeal conflict claim={claim.id} "
                                f"have={claim.appeal_number} "
                                f"got={parsed.appeal_number}"
                            ),
                        )
                    else:
                        await repo.update_claim_fields(
                            session,
                            claim,
                            appeal_number=parsed.appeal_number,
                            status=ClaimStatus.RECEIVED.value,
                            error_text=None,
                        )
                        claim_id = claim.id
                        chat_id = claim.chat_id
                        message_id = claim.message_id
                        matched_kind = IncomingKind.APPEAL
            elif parsed.kind in (IncomingKind.ENTERED, IncomingKind.ALCOHOL):
                match = await match_entered_email(
                    session,
                    parsed=parsed,
                    subject=subject,
                    thread_id=thread_id,
                    in_reply_to=in_reply_to,
                    references=references,
                )
                if not match.claim:
                    label = (
                        "alcohol"
                        if parsed.kind == IncomingKind.ALCOHOL
                        else "entered"
                    )
                    await repo.add_unmatched(
                        session,
                        gmail_id=gmail_id,
                        from_addr=from_addr,
                        subject=subject,
                        snippet=snippet,
                        reason=match.reason,
                    )
                    pending_alert = (
                        f"unmatched:{gmail_id}",
                        (
                            f"Unmatched DocsInBox {label}\n"
                            f"gmail_id={gmail_id}\nfrom={from_addr}\n"
                            f"subject={subject}\nreason={match.reason}\n"
                            f"snippet={snippet}"
                        ),
                    )
                elif parsed.kind == IncomingKind.ALCOHOL:
                    claim = match.claim
                    await repo.update_claim_fields(
                        session,
                        claim,
                        status=ClaimStatus.ALCOHOL.value,
                        error_text=None,
                    )
                    attachments_dir = claim.attachments_dir
                    claim_id = claim.id
                    chat_id = claim.chat_id
                    message_id = claim.message_id
                    matched_kind = IncomingKind.ALCOHOL
                else:
                    claim = match.claim
                    # Ссылку пишем только если в заявке её ещё не было.
                    new_docs = (
                        docs_to_json(parsed.documents)
                        if not _claim_has_doc_links(claim.docs_json)
                        else claim.docs_json
                    )
                    await repo.update_claim_fields(
                        session,
                        claim,
                        status=ClaimStatus.ENTERED.value,
                        docs_json=new_docs,
                        error_text=None,
                    )
                    attachments_dir = claim.attachments_dir
                    claim_id = claim.id
                    chat_id = claim.chat_id
                    message_id = claim.message_id
                    matched_kind = IncomingKind.ENTERED

        if pending_alert:
            await self._alerter.send(
                alert_key=pending_alert[0], text=pending_alert[1]
            )
            return

        if matched_kind == IncomingKind.APPEAL:
            await set_status_reaction(
                self._bot,
                chat_id=chat_id,
                message_id=message_id,
                status=ClaimStatus.RECEIVED,
            )
        elif matched_kind == IncomingKind.ENTERED:
            await set_status_reaction(
                self._bot,
                chat_id=chat_id,
                message_id=message_id,
                status=ClaimStatus.ENTERED,
            )
            cleanup_claim_files(attachments_dir)
        elif matched_kind == IncomingKind.ALCOHOL:
            await set_status_reaction(
                self._bot,
                chat_id=chat_id,
                message_id=message_id,
                status=ClaimStatus.ALCOHOL,
            )
            cleanup_claim_files(attachments_dir)

        if claim_id is not None:
            await self._sync_sheet(claim_id)

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


def _claim_has_doc_links(docs_json: str | None) -> bool:
    try:
        items = json.loads(docs_json or "[]")
    except json.JSONDecodeError:
        return False
    return any(isinstance(item, dict) and item.get("url") for item in items)


def _extract_body(payload: dict) -> str:
    if payload.get("body", {}).get("data"):
        return _decode(payload["body"]["data"])
    parts = payload.get("parts") or []
    texts: list[str] = []
    for part in parts:
        mime = part.get("mimeType", "")
        if mime == "text/plain" and part.get("body", {}).get("data"):
            texts.append(_decode(part["body"]["data"]))
        elif mime.startswith("multipart/"):
            texts.append(_extract_body(part))
        elif mime == "text/html" and part.get("body", {}).get("data") and not texts:
            texts.append(_decode(part["body"]["data"]))
    return "\n".join(texts)


def _decode(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8", errors="replace")
