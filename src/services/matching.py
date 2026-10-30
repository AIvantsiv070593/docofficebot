from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.db import repository as repo
from src.db.models import Claim
from src.parsers.docsinbox import IncomingKind, ParsedIncoming, normalize_subject
from src.statuses import ClaimStatus


@dataclass
class MatchResult:
    claim: Claim | None
    reason: str


async def match_appeal_email(
    session: AsyncSession,
    *,
    subject: str,
    thread_id: str | None,
    in_reply_to: str | None,
    references: str | None,
) -> MatchResult:
    subject_n = normalize_subject(subject)
    by_subject = await repo.find_by_outgoing_subject(
        session, subject_n, statuses=[ClaimStatus.SENT]
    )
    # Also try exact stored subject without normalize differences
    if not by_subject:
        by_subject = await repo.find_by_outgoing_subject(
            session, subject, statuses=[ClaimStatus.SENT]
        )
    if len(by_subject) == 1:
        return MatchResult(by_subject[0], "subject")
    if len(by_subject) > 1:
        return MatchResult(None, "ambiguous_subject")

    if thread_id:
        by_thread = await repo.find_by_thread_id(
            session, thread_id, statuses=[ClaimStatus.SENT]
        )
        if len(by_thread) == 1:
            return MatchResult(by_thread[0], "thread")
        if len(by_thread) > 1:
            return MatchResult(None, "ambiguous_thread")

    if in_reply_to or references:
        hay = f"{in_reply_to or ''} {references or ''}"
        sent = await repo.list_sent_without_appeal(session)
        hits = [c for c in sent if c.gmail_rfc_message_id and c.gmail_rfc_message_id in hay]
        if len(hits) == 1:
            return MatchResult(hits[0], "in_reply_to")

    open_sent = await repo.list_sent_without_appeal(session)
    if len(open_sent) == 1:
        return MatchResult(open_sent[0], "single_open")

    return MatchResult(None, "unmatched_appeal")


async def match_entered_email(
    session: AsyncSession,
    *,
    parsed: ParsedIncoming,
    subject: str,
    thread_id: str | None,
    in_reply_to: str | None,
    references: str | None,
) -> MatchResult:
    if parsed.kind != IncomingKind.ENTERED:
        return MatchResult(None, "not_entered")

    if parsed.appeal_number:
        claim = await repo.find_by_appeal_number(session, parsed.appeal_number)
        if claim:
            return MatchResult(claim, "appeal_number")
        return MatchResult(None, "appeal_not_found")

    # «Уже в системе» может прийти без письма «обращение №» → статус ещё SENT.
    open_statuses = [ClaimStatus.RECEIVED, ClaimStatus.SENT]
    open_values = [s.value for s in open_statuses]

    subject_n = normalize_subject(subject)
    by_subject = await repo.find_by_outgoing_subject(
        session,
        subject_n,
        statuses=open_statuses,
    )
    if not by_subject:
        by_subject = await repo.find_by_outgoing_subject(
            session, subject, statuses=open_statuses
        )

    by_thread: list[Claim] = []
    if thread_id:
        by_thread = await repo.find_by_thread_id(
            session, thread_id, statuses=open_statuses
        )

    if len(by_thread) > 1:
        return MatchResult(None, "ambiguous_thread")

    if len(by_subject) == 1 and len(by_thread) == 1:
        if by_subject[0].id != by_thread[0].id:
            return MatchResult(None, "subject_thread_conflict")
        return MatchResult(by_subject[0], "subject+thread")

    if len(by_subject) == 1:
        return MatchResult(by_subject[0], "subject")
    if len(by_thread) == 1:
        return MatchResult(by_thread[0], "thread")
    if len(by_subject) > 1:
        return MatchResult(None, "ambiguous_subject")

    if in_reply_to or references:
        hay = f"{in_reply_to or ''} {references or ''}"
        from sqlalchemy import select
        from src.db.models import Claim as ClaimModel

        result = await session.execute(
            select(ClaimModel).where(ClaimModel.status.in_(open_values))
        )
        open_claims = list(result.scalars().all())
        hits = [
            c
            for c in open_claims
            if c.gmail_rfc_message_id and c.gmail_rfc_message_id in hay
        ]
        if len(hits) == 1:
            return MatchResult(hits[0], "in_reply_to")

    return MatchResult(None, "unmatched_entered")
