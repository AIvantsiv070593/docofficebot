from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import ReactionTypeEmoji

from src.statuses import STATUS_REACTION, ClaimStatus

logger = logging.getLogger(__name__)


async def set_status_reaction(
    bot: Bot,
    *,
    chat_id: int,
    message_id: int,
    status: ClaimStatus,
) -> None:
    emoji = STATUS_REACTION[status]
    try:
        await bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "failed to set reaction emoji=%s err=%s",
            emoji,
            exc,
            extra={"claim_id": None, "stage": "reaction", "status": status.value},
        )
