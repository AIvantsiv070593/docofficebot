from __future__ import annotations

import base64
import logging
import mimetypes
from email import utils as email_utils
from email.message import EmailMessage
from pathlib import Path

from src.services.gmail_auth import GmailAuth, GmailAuthError

logger = logging.getLogger(__name__)


class GmailSender:
    def __init__(self, auth: GmailAuth, user: str) -> None:
        self._auth = auth
        self._user = user

    def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        attachments: list[Path],
    ) -> tuple[str, str | None, str | None]:
        """Returns (gmail_id, thread_id, rfc822_message_id)."""
        try:
            service = self._auth.build_service()
        except GmailAuthError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._auth.auth_ok = False
            raise GmailAuthError(str(exc)) from exc

        message = EmailMessage()
        message["To"] = to
        message["From"] = self._user
        message["Subject"] = subject
        message.set_content(body)
        rfc_id = email_utils.make_msgid()
        message["Message-ID"] = rfc_id

        for path in attachments:
            ctype, _ = mimetypes.guess_type(path.name)
            maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
            message.add_attachment(
                path.read_bytes(),
                maintype=maintype,
                subtype=subtype,
                filename=path.name,
            )

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        try:
            sent = (
                service.users()
                .messages()
                .send(userId="me", body={"raw": raw})
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            if "invalid_grant" in str(exc).casefold() or "auth" in str(exc).casefold():
                self._auth.auth_ok = False
                raise GmailAuthError(str(exc)) from exc
            raise

        gmail_id = sent.get("id", "")
        thread_id = sent.get("threadId")
        return gmail_id, thread_id, rfc_id
