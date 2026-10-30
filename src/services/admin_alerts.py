from __future__ import annotations

import logging

from aiogram import Bot

from src.config import Settings
from src.db import repository as repo
from src.db.session import session_scope

logger = logging.getLogger(__name__)


class AdminAlerter:
    def __init__(self, bot: Bot, settings: Settings) -> None:
        self._bot = bot
        self._settings = settings

    async def send(
        self,
        *,
        alert_key: str,
        text: str,
        cooldown_seconds: int | None = None,
    ) -> None:
        cooldown = cooldown_seconds or self._settings.admin_alert_cooldown_seconds
        async with session_scope() as session:
            if not await repo.can_send_alert(session, alert_key, cooldown):
                logger.info("admin alert suppressed", extra={"stage": alert_key})
                return
            await repo.record_alert(session, alert_key)

        body = text if text.startswith(("🚨", "⚠️", "✅", "❌", "ℹ️")) else f"🚨 {text}"
        try:
            await self._bot.send_message(
                chat_id=self._settings.admin_telegram_id,
                text=body[:3500],
            )
        except Exception:  # noqa: BLE001
            logger.exception("failed to DM admin")
