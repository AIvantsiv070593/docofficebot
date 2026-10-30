from __future__ import annotations

import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

# Gmail + Sheets — один OAuth-вход под theofficesakh@gmail.com
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/spreadsheets",
]


class GmailAuthError(Exception):
    pass


class GmailAuth:
    def __init__(self, credentials_file: Path, token_file: Path) -> None:
        self._credentials_file = credentials_file
        self._token_file = token_file
        self._creds: Credentials | None = None
        self.auth_ok = True

    def load(self) -> Credentials:
        creds: Credentials | None = None
        if self._token_file.exists():
            creds = Credentials.from_authorized_user_file(
                str(self._token_file), GOOGLE_SCOPES
            )
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self._save(creds)
            except Exception as exc:  # noqa: BLE001
                self.auth_ok = False
                raise GmailAuthError(str(exc)) from exc
        if not creds or not creds.valid:
            self.auth_ok = False
            raise GmailAuthError(
                "Google token missing or invalid; run: python scripts/oauth_gmail.py"
            )
        # Old token without Sheets scope
        granted = set(creds.scopes or [])
        if not set(GOOGLE_SCOPES).issubset(granted) and granted:
            # Some tokens omit scopes in file; still try — API will fail clearly
            missing = set(GOOGLE_SCOPES) - granted
            if missing:
                logger.warning(
                    "token may miss scopes %s — re-run oauth_gmail.py", missing
                )
        self._creds = creds
        self.auth_ok = True
        return creds

    def interactive_login(self) -> Credentials:
        if not self._credentials_file.exists():
            raise GmailAuthError(f"Missing credentials file: {self._credentials_file}")
        flow = InstalledAppFlow.from_client_secrets_file(
            str(self._credentials_file), GOOGLE_SCOPES
        )
        creds = flow.run_local_server(port=0)
        self._save(creds)
        self._creds = creds
        self.auth_ok = True
        return creds

    def credentials(self) -> Credentials:
        return self._creds or self.load()

    def build_service(self):
        creds = self.credentials()
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def build_sheets_service(self):
        creds = self.credentials()
        return build("sheets", "v4", credentials=creds, cache_discovery=False)

    def check_gmail(self) -> tuple[bool, str]:
        """Lightweight Gmail API probe (getProfile)."""
        try:
            profile = (
                self.build_service().users().getProfile(userId="me").execute()
            )
            email = profile.get("emailAddress") or "?"
            self.auth_ok = True
            return True, f"✅ Gmail OK: {email}"
        except GmailAuthError as exc:
            self.auth_ok = False
            return False, f"❌ Gmail FAIL: {_short_err(exc)}"
        except Exception as exc:  # noqa: BLE001
            return False, f"❌ Gmail FAIL: {_short_err(exc)}"

    def check_sheets(self, spreadsheet_id: str) -> tuple[bool, str]:
        """Lightweight Sheets API probe (get title)."""
        try:
            meta = (
                self.build_sheets_service()
                .spreadsheets()
                .get(spreadsheetId=spreadsheet_id, fields="properties.title")
                .execute()
            )
            title = (meta.get("properties") or {}).get("title") or "?"
            self.auth_ok = True
            return True, f"✅ Sheets OK: «{title}»"
        except GmailAuthError as exc:
            self.auth_ok = False
            return False, f"❌ Sheets FAIL: {_short_err(exc)}"
        except Exception as exc:  # noqa: BLE001
            return False, f"❌ Sheets FAIL: {_short_err(exc)}"

    def _save(self, creds: Credentials) -> None:
        self._token_file.parent.mkdir(parents=True, exist_ok=True)
        self._token_file.write_text(creds.to_json(), encoding="utf-8")


def _short_err(exc: BaseException, limit: int = 240) -> str:
    text = str(exc).replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"
