from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Protocol

from src.statuses import STATUS_REACTION, ClaimStatus
from src.timezone_util import format_local

ADMIN_HELP = """🛠 Команды админа (ЛС боту):
📋 /help — этот список
📥 /pending — заявки в работе / ошибки (без «Внесено» и «Исключение»)
🙈 /excluded — заявки со статусом «Исключение»
🍺 /alcohol ID — вручную закрыть заявку как алкоголь (ЕГАИС)
🔁 /retry ID — переотправить заявку со статусом «Ошибка»
🔁 /retry_errors — все «Ошибка», у которых есть файлы на диске
🚫 /exceptions — справочник исключений в Sheets
➕ /exception_add … — добавить исключение
➖ /exception_del N|имя — удалить по номеру из списка или по имени
✉️ /check_gmail — проверка Gmail OAuth/API
📊 /check_sheets — проверка Sheets
🔄 /resync_sheets — очистить реестр Sheets и записать заново из БД
🧹 /purge_errors CONFIRM — удалить все «Ошибка» из БД + папки, затем resync Sheets
🗑 /wipe_all CONFIRM — удалить все заявки в БД + вложения + реестр Sheets

💬 В рабочем чате:
📤 /send … — отправка фото/альбома в DocsInBox"""

_STATUS_ORDER = (
    ClaimStatus.ACCEPTED,
    ClaimStatus.SENT,
    ClaimStatus.RECEIVED,
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


def _format_claims_by_status(
    claims: list[_ClaimLike],
    tz_name: str,
    *,
    title: str,
    status_order: tuple[ClaimStatus, ...] = _STATUS_ORDER,
) -> str:
    by_status: dict[str, list[_ClaimLike]] = defaultdict(list)
    for claim in claims:
        by_status[claim.status].append(claim)

    ordered = [s.value for s in status_order if s.value in by_status]
    ordered.extend(sorted(k for k in by_status if k not in ordered))

    lines = [f"{title}: {len(claims)}"]
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


def format_pending_summary(
    claims: list[_ClaimLike], tz_name: str, *, total_claims: int | None = None
) -> str:
    if not claims:
        if total_claims == 0:
            return "ℹ️ Заявок нет."
        return "✅ Нет заявок в /pending (всё внесено или в исключениях)."

    return _format_claims_by_status(claims, tz_name, title="📥 В работе / ошибки")


def format_excluded_summary(claims: list[_ClaimLike], tz_name: str) -> str:
    if not claims:
        return "ℹ️ Заявок со статусом «Исключение» нет."
    return _format_claims_by_status(
        claims,
        tz_name,
        title="🙈 Исключения (заявки)",
        status_order=(ClaimStatus.EXCEPTION,),
    )


def format_exceptions_list(items: list[str]) -> str:
    if not items:
        return "🚫 Исключений нет.\nДобавить: /exception_add ООО Ромашка"
    lines = [f"🚫 Исключения ({len(items)}):", ""]
    for i, name in enumerate(items, start=1):
        lines.append(f"{i}. {name}")
    lines.append("")
    lines.append("➕ /exception_add …")
    lines.append("➖ /exception_del N  или  /exception_del имя")
    return "\n".join(lines)
