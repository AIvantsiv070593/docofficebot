from types import SimpleNamespace

import pytest
from sqlalchemy import text

from src.db import repository as repo
from src.db.session import init_db, session_scope
from src.services.admin_alerts import AdminAlerter


@pytest.mark.asyncio
async def test_init_db_enables_wal(tmp_path):
    factory = await init_db(tmp_path / "bot.db")
    async with factory() as session:
        mode = (await session.execute(text("PRAGMA journal_mode"))).scalar()
    assert str(mode).lower() == "wal"


@pytest.mark.asyncio
async def test_alert_after_write_commit_does_not_lock(tmp_path):
    """Regression: alert must not open a second write session inside an open txn."""
    await init_db(tmp_path / "bot.db")

    class FakeBot:
        def __init__(self) -> None:
            self.sent: list[dict] = []

        async def send_message(self, **kwargs):
            self.sent.append(kwargs)

    bot = FakeBot()
    settings = SimpleNamespace(
        admin_telegram_id=1,
        admin_alert_cooldown_seconds=0,
    )
    alerter = AdminAlerter(bot, settings)

    async with session_scope() as session:
        await repo.add_unmatched(
            session,
            gmail_id="g1",
            from_addr="a@b.c",
            subject="subj",
            snippet="snip",
            reason="unmatched_appeal",
        )

    await alerter.send(alert_key="unmatched:g1", text="Unmatched")
    assert len(bot.sent) == 1
