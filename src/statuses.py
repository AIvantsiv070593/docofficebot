from __future__ import annotations

from enum import Enum


class ClaimStatus(str, Enum):
    ACCEPTED = "Принято"
    EXCEPTION = "Исключение"
    SENT = "Письмо отправлено"
    RECEIVED = "Получено системой"
    ENTERED = "Внесено"
    NO_REPLY = "Нет ответа"
    ERROR = "Ошибка"


# Bot reactions must be from Telegram ReactionTypeEmoji (not ❌📤📥✅🚫⚠️).
STATUS_REACTION: dict[ClaimStatus, str] = {
    ClaimStatus.ACCEPTED: "👀",
    ClaimStatus.EXCEPTION: "🙈",
    ClaimStatus.SENT: "⚡",
    ClaimStatus.RECEIVED: "🤝",
    ClaimStatus.ENTERED: "👍",
    ClaimStatus.NO_REPLY: "😐",
    ClaimStatus.ERROR: "👎",
}

ACTIVE_STATUSES = frozenset(
    {
        ClaimStatus.ACCEPTED,
        ClaimStatus.SENT,
        ClaimStatus.RECEIVED,
    }
)

FINAL_STATUSES = frozenset(
    {
        ClaimStatus.EXCEPTION,
        ClaimStatus.ENTERED,
        ClaimStatus.NO_REPLY,
        ClaimStatus.ERROR,
    }
)
