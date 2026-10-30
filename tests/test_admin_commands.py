from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot.admin_text import (
    ADMIN_HELP,
    format_exceptions_list,
    format_excluded_summary,
    format_pending_summary,
)
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
        "/excluded",
        "/alcohol",
        "/retry",
        "/retry_errors",
        "/exceptions",
        "/exception_add",
        "/exception_del",
        "/check_gmail",
        "/check_sheets",
        "/resync_sheets",
        "/purge_errors",
        "/wipe_all",
        "/send",
    ):
        assert cmd in ADMIN_HELP
    assert "/link" not in ADMIN_HELP


def test_format_exceptions_list_empty():
    text = format_exceptions_list([])
    assert "Исключений нет" in text
    assert "/exception_add" in text


def test_format_exceptions_list_numbered():
    text = format_exceptions_list(["ООО Ромашка", "ИП Тест"])
    assert "1. ООО Ромашка" in text
    assert "2. ИП Тест" in text
    assert "/exception_del" in text


def test_format_pending_summary_empty_means_all_entered():
    assert "Нет заявок в /pending" in format_pending_summary(
        [], TZ, total_claims=2
    )


def test_format_excluded_summary_empty():
    assert "Исключение" in format_excluded_summary([], TZ)


def test_format_excluded_summary_lists_claims():
    created = datetime(2026, 10, 21, 7, 30, tzinfo=timezone.utc)
    claims = [
        SimpleNamespace(
            id=9,
            status=ClaimStatus.EXCEPTION.value,
            caption="ООО Ромашка №1",
            appeal_number=None,
            created_at=created,
        )
    ]
    text = format_excluded_summary(claims, TZ)
    assert "#9" in text
    assert "ООО Ромашка №1" in text
    assert "🙈" in text


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
    assert "📥 В работе / ошибки: 3" in text
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


async def test_error_claim_not_active_but_findable_for_retry(session):
    session.add(
        Claim(
            chat_id=10,
            message_id=99,
            dedupe_key="msg:99",
            caption="c",
            outgoing_subject="s",
            file_count=1,
            status=ClaimStatus.ERROR.value,
            error_text="Gmail auth",
        )
    )
    await session.commit()
    assert await repo.find_active_by_dedupe(session, 10, "msg:99") is None
    found = await repo.find_by_dedupe(session, 10, "msg:99")
    assert found is not None
    assert found.status == ClaimStatus.ERROR.value
    errors = await repo.list_error_claims(session)
    assert [c.id for c in errors] == [found.id]


async def test_delete_error_claims_only(session):
    session.add(
        Claim(
            chat_id=1,
            message_id=1,
            dedupe_key="e1",
            caption="bad",
            outgoing_subject="s1",
            file_count=1,
            status=ClaimStatus.ERROR.value,
        )
    )
    session.add(
        Claim(
            chat_id=1,
            message_id=2,
            dedupe_key="ok1",
            caption="good",
            outgoing_subject="s2",
            file_count=1,
            status=ClaimStatus.RECEIVED.value,
        )
    )
    await session.commit()
    deleted = await repo.delete_error_claims(session)
    await session.commit()
    assert deleted == [1]
    assert await repo.count_claims(session) == 1
    assert await repo.list_error_claims(session) == []


async def test_find_error_by_outgoing_subject_latest(session):
    for i, subj in enumerate(["other", "PREFIX\\ ИП Тест №1", "PREFIX\\ ИП Тест №1"], start=1):
        session.add(
            Claim(
                chat_id=7,
                message_id=i,
                dedupe_key=f"msg:{i}",
                caption="c",
                outgoing_subject=subj,
                file_count=1,
                status=ClaimStatus.ERROR.value,
            )
        )
    await session.commit()
    found = await repo.find_error_by_outgoing_subject(
        session, 7, "PREFIX\\ ИП Тест №1"
    )
    assert found is not None
    assert found.message_id == 3


async def test_list_not_entered_excludes_entered_and_exception(session):
    for i, status in enumerate(
        [
            ClaimStatus.SENT,
            ClaimStatus.ENTERED,
            ClaimStatus.RECEIVED,
            ClaimStatus.ERROR,
            ClaimStatus.EXCEPTION,
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
    assert ClaimStatus.EXCEPTION.value not in statuses
    assert statuses == {
        ClaimStatus.SENT.value,
        ClaimStatus.RECEIVED.value,
        ClaimStatus.ERROR.value,
    }
    excluded = await repo.list_exception_claims(session)
    assert len(excluded) == 1
    assert excluded[0].status == ClaimStatus.EXCEPTION.value


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
