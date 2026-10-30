from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import AdminAlertLog, Claim, Heartbeat, ProcessedEmail, UnmatchedEmail
from src.statuses import ClaimStatus


async def create_claim(
    session: AsyncSession,
    *,
    chat_id: int,
    message_id: int,
    media_group_id: str | None,
    dedupe_key: str,
    caption: str,
    outgoing_subject: str,
    file_count: int,
    status: ClaimStatus,
    attachments_dir: str | None = None,
) -> Claim:
    claim = Claim(
        chat_id=chat_id,
        message_id=message_id,
        media_group_id=media_group_id,
        dedupe_key=dedupe_key,
        caption=caption,
        outgoing_subject=outgoing_subject,
        file_count=file_count,
        status=status.value,
        attachments_dir=attachments_dir,
        sheets_dirty=True,
    )
    session.add(claim)
    await session.flush()
    return claim


async def get_claim_by_id(session: AsyncSession, claim_id: int) -> Claim | None:
    return await session.get(Claim, claim_id)


async def find_by_dedupe(
    session: AsyncSession, chat_id: int, dedupe_key: str
) -> Claim | None:
    result = await session.execute(
        select(Claim).where(
            Claim.chat_id == chat_id,
            Claim.dedupe_key == dedupe_key,
        )
    )
    return result.scalar_one_or_none()


async def find_active_by_dedupe(
    session: AsyncSession, chat_id: int, dedupe_key: str
) -> Claim | None:
    result = await session.execute(
        select(Claim).where(
            Claim.chat_id == chat_id,
            Claim.dedupe_key == dedupe_key,
            Claim.status.in_(
                [
                    ClaimStatus.ACCEPTED.value,
                    ClaimStatus.SENT.value,
                    ClaimStatus.RECEIVED.value,
                ]
            ),
        )
    )
    return result.scalar_one_or_none()


async def find_by_outgoing_subject(
    session: AsyncSession,
    subject: str,
    statuses: list[ClaimStatus] | None = None,
) -> list[Claim]:
    stmt = select(Claim).where(Claim.outgoing_subject == subject)
    if statuses:
        stmt = stmt.where(Claim.status.in_([s.value for s in statuses]))
    result = await session.execute(stmt.order_by(Claim.created_at.asc()))
    return list(result.scalars().all())


async def find_by_appeal_number(session: AsyncSession, appeal: str) -> Claim | None:
    result = await session.execute(
        select(Claim).where(Claim.appeal_number == appeal).order_by(Claim.id.desc())
    )
    return result.scalars().first()


async def find_by_thread_id(
    session: AsyncSession, thread_id: str, statuses: list[ClaimStatus] | None = None
) -> list[Claim]:
    stmt = select(Claim).where(Claim.gmail_thread_id == thread_id)
    if statuses:
        stmt = stmt.where(Claim.status.in_([s.value for s in statuses]))
    result = await session.execute(stmt.order_by(Claim.created_at.asc()))
    return list(result.scalars().all())


async def list_error_claims(session: AsyncSession) -> list[Claim]:
    result = await session.execute(
        select(Claim)
        .where(Claim.status == ClaimStatus.ERROR.value)
        .order_by(Claim.id.asc())
    )
    return list(result.scalars().all())


async def delete_error_claims(session: AsyncSession) -> list[int]:
    claims = await list_error_claims(session)
    ids = [c.id for c in claims]
    for claim in claims:
        await session.delete(claim)
    await session.flush()
    return ids


async def find_error_by_outgoing_subject(
    session: AsyncSession, chat_id: int, outgoing_subject: str
) -> Claim | None:
    """Latest ERROR claim with the same mail subject (same invoice text)."""
    result = await session.execute(
        select(Claim)
        .where(
            Claim.chat_id == chat_id,
            Claim.outgoing_subject == outgoing_subject,
            Claim.status == ClaimStatus.ERROR.value,
        )
        .order_by(Claim.id.desc())
    )
    return result.scalars().first()


async def list_sent_without_appeal(session: AsyncSession) -> list[Claim]:
    result = await session.execute(
        select(Claim)
        .where(
            Claim.status == ClaimStatus.SENT.value,
            Claim.appeal_number.is_(None),
        )
        .order_by(Claim.created_at.asc())
    )
    return list(result.scalars().all())


async def list_not_entered(session: AsyncSession) -> list[Claim]:
    """Claims still in progress / failed — not closed finals."""
    result = await session.execute(
        select(Claim)
        .where(
            Claim.status.notin_(
                [
                    ClaimStatus.ENTERED.value,
                    ClaimStatus.EXCEPTION.value,
                    ClaimStatus.ALCOHOL.value,
                ]
            )
        )
        .order_by(Claim.created_at.asc())
    )
    return list(result.scalars().all())


async def list_exception_claims(session: AsyncSession) -> list[Claim]:
    result = await session.execute(
        select(Claim)
        .where(Claim.status == ClaimStatus.EXCEPTION.value)
        .order_by(Claim.created_at.asc())
    )
    return list(result.scalars().all())


async def count_claims(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(Claim))
    return int(result.scalar_one())


async def list_resend_candidates(
    session: AsyncSession, *, older_than: datetime, max_attempts: int
) -> list[Claim]:
    result = await session.execute(
        select(Claim).where(
            Claim.status == ClaimStatus.SENT.value,
            Claim.appeal_number.is_(None),
            Claim.last_sent_at.is_not(None),
            Claim.last_sent_at <= older_than,
            Claim.resend_count < max_attempts,
        )
    )
    return list(result.scalars().all())


async def list_dirty_claims(
    session: AsyncSession, limit: int | None = 50
) -> list[Claim]:
    stmt = select(Claim).where(Claim.sheets_dirty.is_(True)).order_by(Claim.id.asc())
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def mark_all_for_sheet_resync(session: AsyncSession) -> int:
    result = await session.execute(
        update(Claim).values(sheet_row=None, sheets_dirty=True)
    )
    return int(result.rowcount or 0)


async def wipe_operational_data(session: AsyncSession) -> dict[str, int]:
    claims = await session.execute(delete(Claim))
    emails = await session.execute(delete(ProcessedEmail))
    unmatched = await session.execute(delete(UnmatchedEmail))
    alerts = await session.execute(delete(AdminAlertLog))
    return {
        "claims": int(claims.rowcount or 0),
        "processed_emails": int(emails.rowcount or 0),
        "unmatched_emails": int(unmatched.rowcount or 0),
        "admin_alerts": int(alerts.rowcount or 0),
    }


async def update_claim_fields(session: AsyncSession, claim: Claim, **fields: object) -> Claim:
    for key, value in fields.items():
        setattr(claim, key, value)
    claim.sheets_dirty = True
    claim.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return claim


async def mark_email_processed(
    session: AsyncSession,
    gmail_id: str,
    *,
    kind: str,
    claim_id: int | None,
) -> bool:
    existing = await session.get(ProcessedEmail, gmail_id)
    if existing:
        return False
    session.add(
        ProcessedEmail(gmail_id=gmail_id, kind=kind, claim_id=claim_id)
    )
    await session.flush()
    return True


async def is_email_processed(session: AsyncSession, gmail_id: str) -> bool:
    return (await session.get(ProcessedEmail, gmail_id)) is not None


async def add_unmatched(
    session: AsyncSession,
    *,
    gmail_id: str,
    from_addr: str,
    subject: str,
    snippet: str,
    reason: str,
) -> UnmatchedEmail:
    row = UnmatchedEmail(
        gmail_id=gmail_id,
        from_addr=from_addr,
        subject=subject,
        snippet=snippet,
        reason=reason,
    )
    session.add(row)
    await session.flush()
    return row


async def resolve_unmatched_by_gmail_id(session: AsyncSession, gmail_id: str) -> None:
    result = await session.execute(
        select(UnmatchedEmail).where(UnmatchedEmail.gmail_id == gmail_id)
    )
    row = result.scalar_one_or_none()
    if row:
        row.resolved = True


async def can_send_alert(
    session: AsyncSession, alert_key: str, cooldown_seconds: int
) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=cooldown_seconds)
    result = await session.execute(
        select(AdminAlertLog)
        .where(AdminAlertLog.alert_key == alert_key, AdminAlertLog.sent_at >= cutoff)
        .order_by(AdminAlertLog.sent_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none() is None


async def record_alert(session: AsyncSession, alert_key: str) -> None:
    session.add(AdminAlertLog(alert_key=alert_key))
    await session.flush()


async def touch_heartbeat(session: AsyncSession, name: str) -> None:
    row = await session.get(Heartbeat, name)
    now = datetime.now(timezone.utc)
    if row is None:
        session.add(Heartbeat(name=name, updated_at=now))
    else:
        row.updated_at = now
    await session.flush()


async def get_heartbeat(session: AsyncSession, name: str) -> Heartbeat | None:
    return await session.get(Heartbeat, name)


async def mark_sheet_synced(session: AsyncSession, claim_id: int, sheet_row: int) -> None:
    await session.execute(
        update(Claim)
        .where(Claim.id == claim_id)
        .values(sheet_row=sheet_row, sheets_dirty=False)
    )
