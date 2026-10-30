import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.db.models import Base, Claim
from src.parsers.docsinbox import IncomingKind, ParsedIncoming
from src.services.matching import match_appeal_email, match_entered_email
from src.statuses import ClaimStatus


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def test_match_appeal_by_subject(session):
    session.add(
        Claim(
            chat_id=1,
            message_id=10,
            dedupe_key="a",
            caption="ИП БАТУРИН, №2744",
            outgoing_subject="ООО Сфофрендз инн 6501291591\\ ИП БАТУРИН, №2744",
            file_count=1,
            status=ClaimStatus.SENT.value,
        )
    )
    await session.commit()

    result = await match_appeal_email(
        session,
        subject="ООО Сфофрендз инн 6501291591\\ ИП БАТУРИН, №2744",
        thread_id=None,
        in_reply_to=None,
        references=None,
    )
    assert result.claim is not None
    assert result.reason == "subject"


async def test_match_entered_by_subject_when_no_appeal_in_body(session):
    session.add(
        Claim(
            chat_id=1,
            message_id=10,
            dedupe_key="a",
            caption="ИП БАТУРИН, №2744",
            outgoing_subject="ООО Сфофрендз инн 6501291591\\ ИП БАТУРИН, №2744",
            file_count=1,
            status=ClaimStatus.RECEIVED.value,
            appeal_number="059137937",
        )
    )
    await session.commit()

    parsed = ParsedIncoming(kind=IncomingKind.ENTERED, appeal_number=None, documents=[])
    result = await match_entered_email(
        session,
        parsed=parsed,
        subject="ООО Сфофрендз инн 6501291591\\ ИП БАТУРИН, №2744",
        thread_id=None,
        in_reply_to=None,
        references=None,
    )
    assert result.claim is not None
    assert result.claim.appeal_number == "059137937"


async def test_match_entered_from_sent_when_already_in_system(session):
    """«Уже в системе» может прийти без письма «обращение №» — статус ещё SENT."""
    session.add(
        Claim(
            chat_id=1,
            message_id=10,
            dedupe_key="a",
            caption="ИП БАТУРИН, №2744",
            outgoing_subject="ООО Сфофрендз инн 6501291591\\ ИП БАТУРИН, №2744",
            file_count=1,
            status=ClaimStatus.SENT.value,
        )
    )
    await session.commit()

    parsed = ParsedIncoming(kind=IncomingKind.ENTERED, appeal_number=None, documents=[])
    result = await match_entered_email(
        session,
        parsed=parsed,
        subject="ООО Сфофрендз инн 6501291591\\ ИП БАТУРИН, №2744",
        thread_id=None,
        in_reply_to=None,
        references=None,
    )
    assert result.claim is not None
    assert result.reason == "subject"


async def test_match_entered_prefers_unique_thread_when_subject_ambiguous(session):
    subject = "ООО Сфофрендз инн 6501291591\\ ИП БАТУРИН, №2744"
    session.add(
        Claim(
            chat_id=1,
            message_id=10,
            dedupe_key="a",
            caption="old",
            outgoing_subject=subject,
            file_count=1,
            status=ClaimStatus.RECEIVED.value,
            gmail_thread_id="thread-other",
        )
    )
    session.add(
        Claim(
            chat_id=1,
            message_id=11,
            dedupe_key="b",
            caption="new",
            outgoing_subject=subject,
            file_count=1,
            status=ClaimStatus.SENT.value,
            gmail_thread_id="thread-hit",
        )
    )
    await session.commit()

    parsed = ParsedIncoming(kind=IncomingKind.ENTERED, appeal_number=None, documents=[])
    result = await match_entered_email(
        session,
        parsed=parsed,
        subject=subject,
        thread_id="thread-hit",
        in_reply_to=None,
        references=None,
    )
    assert result.claim is not None
    assert result.claim.gmail_thread_id == "thread-hit"
    assert result.reason == "thread"


async def test_match_entered_ambiguous_subject(session):
    subject = "ООО Сфофрендз инн 6501291591\\ ИП БАТУРИН, №2744"
    session.add_all(
        [
            Claim(
                chat_id=1,
                message_id=10,
                dedupe_key="a",
                caption="x",
                outgoing_subject=subject,
                file_count=1,
                status=ClaimStatus.SENT.value,
            ),
            Claim(
                chat_id=1,
                message_id=11,
                dedupe_key="b",
                caption="y",
                outgoing_subject=subject,
                file_count=1,
                status=ClaimStatus.RECEIVED.value,
                appeal_number="1",
            ),
        ]
    )
    await session.commit()

    parsed = ParsedIncoming(kind=IncomingKind.ENTERED, appeal_number=None, documents=[])
    result = await match_entered_email(
        session,
        parsed=parsed,
        subject=subject,
        thread_id=None,
        in_reply_to=None,
        references=None,
    )
    assert result.claim is None
    assert result.reason == "ambiguous_subject"


async def test_match_entered_by_appeal_number(session):
    session.add(
        Claim(
            chat_id=1,
            message_id=10,
            dedupe_key="a",
            caption="x",
            outgoing_subject="subj",
            file_count=1,
            status=ClaimStatus.RECEIVED.value,
            appeal_number="059137937",
        )
    )
    await session.commit()

    parsed = ParsedIncoming(
        kind=IncomingKind.ENTERED, appeal_number="059137937", documents=[]
    )
    result = await match_entered_email(
        session,
        parsed=parsed,
        subject="other",
        thread_id=None,
        in_reply_to=None,
        references=None,
    )
    assert result.reason == "appeal_number"
    assert result.claim is not None
