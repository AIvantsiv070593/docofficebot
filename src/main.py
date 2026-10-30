from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher

from src.bot.handlers import build_router
from src.config import get_settings
from src.db.session import init_db, session_scope
from src.db import repository as repo
from src.logging_setup import setup_logging
from src.services.admin_alerts import AdminAlerter
from src.services.claim_pipeline import ClaimPipeline
from src.services.exceptions_service import ExceptionsCache
from src.services.gmail_auth import GmailAuth
from src.services.gmail_poller import GmailPoller
from src.services.gmail_sender import GmailSender
from src.services.jobs import BackgroundJobs
from src.services.sheets import SheetsRegistry

logger = logging.getLogger(__name__)


async def _loop_call(period: float, coro_factory, name: str) -> None:
    while True:
        try:
            await coro_factory()
        except Exception:  # noqa: BLE001
            logger.exception("background job failed name=%s", name)
        await asyncio.sleep(period)


async def run() -> None:
    setup_logging()
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.claims_dir.mkdir(parents=True, exist_ok=True)
    settings.backups_dir.mkdir(parents=True, exist_ok=True)

    await init_db(settings.database_path)

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

    gmail_auth = GmailAuth(settings.gmail_credentials_file, settings.gmail_token_file)
    try:
        gmail_auth.load()
    except Exception as exc:  # noqa: BLE001
        logger.warning("gmail auth not ready at startup: %s", exc)
        gmail_auth.auth_ok = False

    sheets = SheetsRegistry(settings, gmail_auth)
    exceptions_cache = ExceptionsCache(settings.exceptions_cache_ttl_seconds)
    alerter = AdminAlerter(bot, settings)
    gmail_sender = GmailSender(gmail_auth, settings.gmail_user)

    pipeline = ClaimPipeline(
        bot=bot,
        settings=settings,
        sheets=sheets,
        exceptions_cache=exceptions_cache,
        gmail_sender=gmail_sender,
        alerter=alerter,
        gmail_auth_ok=lambda: gmail_auth.auth_ok,
    )
    poller = GmailPoller(
        auth=gmail_auth,
        settings=settings,
        sheets=sheets,
        alerter=alerter,
        bot=bot,
    )
    jobs = BackgroundJobs(
        settings=settings,
        gmail_sender=gmail_sender,
        sheets=sheets,
        alerter=alerter,
        bot=bot,
    )

    router = build_router(
        settings=settings,
        pipeline=pipeline,
        gmail_auth=gmail_auth,
        jobs=jobs,
        sheets=sheets,
        exceptions_cache=exceptions_cache,
    )
    dp.include_router(router)

    async def heartbeat() -> None:
        async with session_scope() as session:
            await repo.touch_heartbeat(session, "main")
        await jobs.health_check()

    bg_tasks = [
        asyncio.create_task(
            _loop_call(settings.gmail_poll_interval_seconds, poller.poll_once, "gmail_poll")
        ),
        asyncio.create_task(_loop_call(3600, jobs.resend_stale, "resend")),
        asyncio.create_task(
            _loop_call(
                settings.sheets_sync_interval_seconds,
                jobs.sync_dirty_sheets,
                "sheets_sync",
            )
        ),
        asyncio.create_task(_loop_call(86400, jobs.cleanup_orphan_claims, "orphan_cleanup")),
        asyncio.create_task(_loop_call(300, heartbeat, "heartbeat")),
    ]

    logger.info("DocOfficeBot starting")
    try:
        await dp.start_polling(bot)
    finally:
        for task in bg_tasks:
            task.cancel()
        await bot.session.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
