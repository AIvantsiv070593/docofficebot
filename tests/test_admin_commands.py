from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot.admin_text import ADMIN_HELP, format_pending_summary
from src.db import repository as repo
from src.db.models import Base, Claim, ProcessedEmail, UnmatchedEmail
from src.statuses import ClaimStatus

TZ = "Asia/Sakhalin"


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def test_admin_help_lists_commands():
    for cmd in (
        "/help",
        "/pending",
        "/check_gmail",
        "/check_sheets",
        "/resync_sheets",
        "/wipe_all",
        "/send",
    ):
        assert cmd in ADMIN_HELP
    assert "/link" not in ADMIN_HELP


def test_format_pending_summary_empty_means_all_entered():
    assert (
        format_pending_summary([], TZ, total_claims=2)
        == "✅ Все заявки в статусе «Внесено»."
    )


def test_format_pending_summary_no_claims_at_all():
    assert format_pending_summary([], TZ, total_claims=0) == "ℹ️ Заявок нет."


def test_format_pending_summary_groups_by_status():
    created = datetime(2026, 10, 21, 7, 30, tzinfo=timezone.utc)
    claims = [
        SimpleNamespace(
            id=1,
            status=ClaimStatus.SENT.value,
            caption="А №1",
            appeal_number=None,
            created_at=created,
        ),
        SimpleNamespace(
            id=2,
            status=ClaimStatus.RECEIVED.value,
            caption="Б №2",
            appeal_number="123",
            created_at=created,
        ),
        SimpleNamespace(
            id=3,
            status=ClaimStatus.SENT.value,
            caption="В №3",
            appeal_number=None,
            created_at=created,
        ),
    ]
    text = format_pending_summary(claims, TZ)
    assert "📥 Не внесено: 3" in text
    assert f"· ⚡ {ClaimStatus.SENT.value} — 2" in text
    assert f"—— ⚡ {ClaimStatus.SENT.value} (2) ——" in text
    assert "#1  📅 21.10.2026 18:30" in text
    assert "📎 А №1" in text
    assert "#2  📅 21.10.2026 18:30" in text
    assert "🔢 обращение 123" in text


async def test_count_claims(session):
    assert await repo.count_claims(session) == 0
    session.add(
        Claim(
            chat_id=1,
            message_id=1,
            dedupe_key="d1",
            caption="c",
            outgoing_subject="s",
            file_count=1,
            status=ClaimStatus.ENTERED.value,
        )
    )
    await session.commit()
    assert await repo.count_claims(session) == 1


async def test_list_not_entered_excludes_entered(session):
    for i, status in enumerate(
        [
            ClaimStatus.SENT,
            ClaimStatus.ENTERED,
            ClaimStatus.RECEIVED,
            ClaimStatus.ERROR,
        ],
        start=1,
    ):
        session.add(
            Claim(
                chat_id=1,
                message_id=i,
                dedupe_key=f"k{i}",
                caption=f"c{i}",
                outgoing_subject=f"s{i}",
                file_count=1,
                status=status.value,
            )
        )
    await session.commit()

    rows = await repo.list_not_entered(session)
    statuses = {c.status for c in rows}
    assert ClaimStatus.ENTERED.value not in statuses
    assert statuses == {
        ClaimStatus.SENT.value,
        ClaimStatus.RECEIVED.value,
        ClaimStatus.ERROR.value,
    }


async def test_mark_all_for_sheet_resync(session):
    session.add(
        Claim(
            chat_id=1,
            message_id=1,
            dedupe_key="k1",
            caption="c",
            outgoing_subject="s",
            file_count=1,
            status=ClaimStatus.SENT.value,
            sheet_row=5,
            sheets_dirty=False,
        )
    )
    await session.commit()

    n = await repo.mark_all_for_sheet_resync(session)
    await session.commit()
    assert n == 1
    claim = await repo.get_claim_by_id(session, 1)
    assert claim is not None
    assert claim.sheet_row is None
    assert claim.sheets_dirty is True


async def test_wipe_operational_data(session):
    session.add(
        Claim(
            chat_id=1,
            message_id=1,
            dedupe_key="k1",
            caption="c",
            outgoing_subject="s",
            file_count=1,
            status=ClaimStatus.SENT.value,
        )
    )
    session.add(ProcessedEmail(gmail_id="g1", kind="appeal", claim_id=1))
    session.add(
        UnmatchedEmail(
            gmail_id="g2",
            from_addr="a@b.c",
            subject="s",
            snippet="",
            reason="x",
        )
    )
    await session.commit()

    counts = await repo.wipe_operational_data(session)
    await session.commit()
    assert counts["claims"] == 1
    assert counts["processed_emails"] == 1
    assert counts["unmatched_emails"] == 1
    assert await repo.list_not_entered(session) == []
