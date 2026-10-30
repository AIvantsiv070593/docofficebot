from src.statuses import STATUS_REACTION, ClaimStatus

# Subset of Telegram Bot API ReactionTypeEmoji — must stay in that list.
_ALLOWED = frozenset("👀🙈⚡🤝👍😐👎")


def test_status_reactions_are_telegram_bot_allowed():
    assert set(STATUS_REACTION) == set(ClaimStatus)
    for status, emoji in STATUS_REACTION.items():
        assert emoji in _ALLOWED, f"{status.value} → {emoji!r} not allowed for bots"
