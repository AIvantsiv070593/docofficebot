from __future__ import annotations

import re
from typing import Any

MENTION_RE = re.compile(r"@\w+", re.UNICODE)
SEND_CMD_RE = re.compile(
    r"(?i)^\s*/send(?:@\w+)?(?:\s+|$)",
)


def extract_caption(message: Any) -> str:
    return (message.caption or message.text or "").strip()


def clean_claim_caption(caption: str) -> str:
    """Strip /send and @mentions; leftover is counterparty + invoice no."""
    text = caption or ""
    text = SEND_CMD_RE.sub(" ", text, count=1)
    text = MENTION_RE.sub(" ", text)
    return " ".join(text.split()).strip()


# Backwards-compatible alias
def caption_without_mentions(caption: str) -> str:
    return clean_claim_caption(caption)


def has_send_command(message: Any) -> bool:
    """True if caption/text starts with /send or has bot_command entity /send."""
    caption = extract_caption(message)
    if SEND_CMD_RE.match(caption):
        return True
    entities = list(getattr(message, "caption_entities", None) or []) + list(
        getattr(message, "entities", None) or []
    )
    for entity in entities:
        if entity.type != "bot_command":
            continue
        chunk = caption[entity.offset : entity.offset + entity.length]
        if chunk.casefold().startswith("/send"):
            return True
    return False


def build_outgoing_subject(prefix: str, caption_clean: str) -> str:
    return f"{prefix}\\ {caption_clean}".strip()
