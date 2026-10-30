from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = (
        UniqueConstraint("chat_id", "dedupe_key", name="uq_claims_chat_dedupe"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(Integer, index=True)
    message_id: Mapped[int] = mapped_column(Integer)
    media_group_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(128))
    caption: Mapped[str] = mapped_column(Text, default="")
    outgoing_subject: Mapped[str] = mapped_column(Text, default="")
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(64), index=True)
    appeal_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    docs_json: Mapped[str] = mapped_column(Text, default="[]")
    error_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sheet_row: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sheets_dirty: Mapped[bool] = mapped_column(Boolean, default=True)
    gmail_message_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    gmail_thread_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)
    gmail_rfc_message_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    attachments_dir: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attachments_compressed: Mapped[bool] = mapped_column(Boolean, default=False)
    resend_count: Mapped[int] = mapped_column(Integer, default=0)
    last_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProcessedEmail(Base):
    __tablename__ = "processed_emails"

    gmail_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    kind: Mapped[str] = mapped_column(String(64), default="")
    claim_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class UnmatchedEmail(Base):
    __tablename__ = "unmatched_emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gmail_id: Mapped[str] = mapped_column(String(256), unique=True)
    from_addr: Mapped[str] = mapped_column(String(256), default="")
    subject: Mapped[str] = mapped_column(Text, default="")
    snippet: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AdminAlertLog(Base):
    __tablename__ = "admin_alert_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_key: Mapped[str] = mapped_column(String(256), index=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Heartbeat(Base):
    __tablename__ = "heartbeat"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
