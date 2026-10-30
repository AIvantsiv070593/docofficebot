from src.services.exceptions_service import (
    ExceptionsCache,
    is_exception,
    normalize_counterparty,
)


def test_exception_substring_casefold():
    exceptions = ["ООО Ромашка", "ООО Гильдия Алко"]
    assert is_exception("накладная ооо ромашка №12", exceptions)
    assert is_exception("ООО Гильдия Алко, №1", exceptions)
    assert is_exception('ООО "Гильдия" Алко №5', exceptions)
    assert is_exception("ООО «Гильдия» Алко", exceptions)
    assert not is_exception("ИП БАТУРИН, №2744", exceptions)


def test_normalize():
    assert normalize_counterparty("  ООО   Ромашка ") == "ооо ромашка"
    assert normalize_counterparty('ООО "Гильдия" Алко') == "ооо гильдия алко"
    assert normalize_counterparty("ООО «Гильдия» Алко") == "ооо гильдия алко"


def test_exceptions_cache_invalidate():
    cache = ExceptionsCache(ttl_seconds=60)
    cache.set(["А"])
    assert cache.get_if_fresh() == ["А"]
    cache.invalidate()
    assert cache.get_if_fresh() is None
