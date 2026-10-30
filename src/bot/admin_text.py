from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Protocol

from src.statuses import STATUS_REACTION, ClaimStatus
from src.timezone_util import format_local

ADMIN_HELP = """🛠 Команды админа (ЛС боту):
📋 /help — этот список
📥 /pending — заявки не в статусе «Внесено»
✉️ /check_gmail — проверка Gmail OAuth/API
📊 /check_sheets — проверка Sheets
🔄 /resync_sheets — очистить реестр Sheets и записать заново из БД
🗑 /wipe_all CONFIRM — удалить все заявки в БД + вложения + реестр Sheets

💬 В рабочем чате:
📤 /send … — отправка фото/альбома в DocsInBox"""

_STATUS_ORDER = (
    ClaimStatus.ACCEPTED,
    ClaimStatus.SENT,
    ClaimStatus.RECEIVED,
    ClaimStatus.EXCEPTION,
    ClaimStatus.NO_REPLY,
    ClaimStatus.ERROR,
)

# shortcut: Telegram message limit; long queues get truncated after ~30 claims
_MAX_CLAIMS = 30


class _ClaimLike(Protocol):
    id: int
    status: str
    caption: str
    appeal_number: str | None
    created_at: datetime | None


def _status_title(status: str) -> str:
    try:
        emoji = STATUS_REACTION[ClaimStatus(status)]
    except ValueError:
        return status
    return f"{emoji} {status}"


def format_pending_summary(
    claims: list[_ClaimLike], tz_name: str, *, total_claims: int | None = None
) -> str:
    if not claims:
        if total_claims == 0:
            return "ℹ️ Заявок нет."
        return "✅ Все заявки в статусе «Внесено»."

    by_status: dict[str, list[_ClaimLike]] = defaultdict(list)
    for claim in claims:
        by_status[claim.status].append(claim)

    ordered = [s.value for s in _STATUS_ORDER if s.value in by_status]
    ordered.extend(sorted(k for k in by_status if k not in ordered))

    lines = [f"📥 Не внесено: {len(claims)}"]
    for status in ordered:
        lines.append(f"· {_status_title(status)} — {len(by_status[status])}")
    lines.append("")

    shown = 0
    for status in ordered:
        group = by_status[status]
        lines.append(f"—— {_status_title(status)} ({len(group)}) ——")
        for claim in group:
            if shown >= _MAX_CLAIMS:
                lines.append("")
                lines.append(f"… и ещё {len(claims) - shown}")
                return "\n".join(lines)
            when = format_local(claim.created_at, tz_name)
            caption = (claim.caption or "").strip() or "—"
            if len(caption) > 80:
                caption = caption[:77] + "…"
            lines.append(f"#{claim.id}  📅 {when}")
            lines.append(f"📎 {caption}")
            if claim.appeal_number:
                lines.append(f"🔢 обращение {claim.appeal_number}")
            lines.append("")
            shown += 1

    return "\n".join(lines).rstrip()
