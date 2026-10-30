from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


APPEAL_RE = re.compile(
    r"обращение\s*№\s*(\d+)",
    re.IGNORECASE,
)
ENTERED_MARKERS = (
    "накладная была обработана",
    "ссылки на созданные документы",
    "документ уже есть в системе",
    "ранее был выгружен в систему",
)
ALCOHOL_MARKERS = (
    "алкогольных накладных",
    "ручной ввод не подходит для алкогольных",
    "отчётность по алкоголю",
    "отчетность по алкоголю",
)
DOC_LINE_RE = re.compile(
    r"Накладная\s*№\s*([^\s]+)\s*от\s*(\d{2}\.\d{2}\.\d{4}).*?"
    r"\((https://dxbx\.ru/[^)\s]+)\)",
    re.IGNORECASE | re.DOTALL,
)
# «Документ 56241 от 12.10.2026 00:00 ранее был выгружен …: https://dxbx.ru/…»
# (время после даты опционально — иначе `:` в 00:00 ломает разбор)
ALREADY_DOC_RE = re.compile(
    r"Документ\s+(\d+)\s+от\s+(\d{2}\.\d{2}\.\d{4})"
    r"(?:\s+\d{1,2}:\d{2})?\s+ранее был выгружен в систему:\s*"
    r"(https://dxbx\.ru/[^\s)>\"]+)",
    re.IGNORECASE,
)
DXBX_ID_RE = re.compile(r"/invoice/(\d+)", re.IGNORECASE)


class IncomingKind(str, Enum):
    APPEAL = "appeal"
    ENTERED = "entered"
    ALCOHOL = "alcohol"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DocInfo:
    sp_number: str
    date: str
    url: str
    dxbx_id: str | None


@dataclass(frozen=True)
class ParsedIncoming:
    kind: IncomingKind
    appeal_number: str | None = None
    documents: list[DocInfo] = field(default_factory=list)


def parse_incoming_email(*, subject: str, body: str) -> ParsedIncoming:
    text = body or ""
    lowered = text.casefold()

    appeal_match = APPEAL_RE.search(text)
    if appeal_match and "зафиксировали" in lowered:
        return ParsedIncoming(
            kind=IncomingKind.APPEAL,
            appeal_number=appeal_match.group(1),
        )

    if any(marker in lowered for marker in ALCOHOL_MARKERS):
        return ParsedIncoming(kind=IncomingKind.ALCOHOL)

    if any(marker in lowered for marker in ENTERED_MARKERS):
        documents = _extract_documents(text)
        appeal_in_body = appeal_match.group(1) if appeal_match else None
        return ParsedIncoming(
            kind=IncomingKind.ENTERED,
            appeal_number=appeal_in_body,
            documents=documents,
        )

    return ParsedIncoming(kind=IncomingKind.UNKNOWN)


def _doc_from_groups(sp_number: str, date: str, url: str) -> DocInfo:
    dxbx = DXBX_ID_RE.search(url)
    return DocInfo(
        sp_number=sp_number,
        date=date,
        url=url,
        dxbx_id=dxbx.group(1) if dxbx else None,
    )


def _extract_documents(text: str) -> list[DocInfo]:
    docs: list[DocInfo] = []
    for match in DOC_LINE_RE.finditer(text):
        docs.append(_doc_from_groups(match.group(1), match.group(2), match.group(3)))
    for match in ALREADY_DOC_RE.finditer(text):
        docs.append(_doc_from_groups(match.group(1), match.group(2), match.group(3)))
    if docs:
        return list({d.url: d for d in docs}.values())

    # Fallback: collect bare dxbx links
    for url_match in re.finditer(r"(https://dxbx\.ru/[^\s)>\"]+)", text):
        docs.append(_doc_from_groups("", "", url_match.group(1)))
    return list({d.url: d for d in docs}.values())


def normalize_subject(subject: str) -> str:
    return " ".join((subject or "").split())
