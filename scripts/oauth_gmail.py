#!/usr/bin/env python3
"""One-time Google OAuth (Gmail + Sheets). Saves token to data/gmail_token.json."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import get_settings
from src.services.gmail_auth import GmailAuth


def main() -> None:
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    auth = GmailAuth(settings.gmail_credentials_file, settings.gmail_token_file)
    creds = auth.interactive_login()
    print(f"Saved token to {settings.gmail_token_file}")
    print(f"valid={creds.valid} has_refresh={bool(creds.refresh_token)}")
    print(f"scopes={list(creds.scopes or [])}")
    print("В браузере войдите в аккаунт GMAIL_USER и разрешите Gmail + Sheets.")


if __name__ == "__main__":
    main()
