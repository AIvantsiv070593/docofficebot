from __future__ import annotations

import json
import logging

from src.config import Settings
from src.db.models import Claim
from src.services.gmail_auth import GmailAuth, GmailAuthError
from src.timezone_util import format_local

logger = logging.getLogger(__name__)

REGISTRY_HEADERS = [
    "Дата",
    "Контрагент / накладная",
    "Файлов",
    "Статус",
    "№ обращения",
    "Документ DocsInBox",
    "Ссылка",
    "Ошибка",
]


class SheetsRegistry:
    """Google Sheets via the same OAuth token as Gmail (no service account)."""

    def __init__(self, settings: Settings, auth: GmailAuth) -> None:
        self._settings = settings
        self._auth = auth

    @property
    def enabled(self) -> bool:
        return self._auth.auth_ok

    def _values(self):
        try:
            service = self._auth.build_sheets_service()
        except GmailAuthError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._auth.auth_ok = False
            raise GmailAuthError(str(exc)) from exc
        return service.spreadsheets().values()

    def list_exceptions(self) -> list[str]:
        if not self.enabled:
            return []
        result = (
            self._values()
            .get(
                spreadsheetId=self._settings.spreadsheet_id,
                range=f"{self._settings.sheets_exceptions_tab}!A:A",
            )
            .execute()
        )
        rows = result.get("values", [])
        items: list[str] = []
        for row in rows:
            if not row:
                continue
            value = str(row[0]).strip()
            if value and value.casefold() not in {"исключения", "контрагент", "название"}:
                items.append(value)
        return items

    def clear_registry(self) -> None:
        """Wipe registry tab data and restore header row."""
        if not self.enabled:
            raise GmailAuthError("Sheets unavailable")
        tab = self._settings.sheets_registry_tab
        sid = self._settings.spreadsheet_id
        self._values().clear(
            spreadsheetId=sid,
            range=f"{tab}!A:H",
        ).execute()
        self._values().update(
            spreadsheetId=sid,
            range=f"{tab}!A1:H1",
            valueInputOption="RAW",
            body={"values": [REGISTRY_HEADERS]},
        ).execute()

    def upsert_claim_row(self, claim: Claim) -> int:
        if not self.enabled:
            return claim.sheet_row or 0

        local_dt = format_local(claim.created_at, self._settings.timezone)

        docs = []
        links = []
        try:
            parsed = json.loads(claim.docs_json or "[]")
            for item in parsed:
                if item.get("sp_number"):
                    docs.append(item["sp_number"])
                if item.get("url"):
                    links.append(item["url"])
        except json.JSONDecodeError:
            pass

        row = [
            local_dt,
            claim.caption,
            str(claim.file_count),
            claim.status,
            claim.appeal_number or "",
            "; ".join(docs),
            "; ".join(links),
            claim.error_text or "",
        ]

        if claim.sheet_row:
            range_name = (
                f"{self._settings.sheets_registry_tab}!A{claim.sheet_row}:H{claim.sheet_row}"
            )
            self._values().update(
                spreadsheetId=self._settings.spreadsheet_id,
                range=range_name,
                valueInputOption="RAW",
                body={"values": [row]},
            ).execute()
            return claim.sheet_row

        append = (
            self._values()
            .append(
                spreadsheetId=self._settings.spreadsheet_id,
                range=f"{self._settings.sheets_registry_tab}!A:H",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]},
            )
            .execute()
        )
        updated = append.get("updates", {}).get("updatedRange", "")
        try:
            cell = updated.split("!")[-1]
            row_num = int("".join(ch for ch in cell.split(":")[0] if ch.isdigit()))
            return row_num
        except Exception:  # noqa: BLE001
            logger.warning("could not parse sheet row from %s", updated)
            return 0
