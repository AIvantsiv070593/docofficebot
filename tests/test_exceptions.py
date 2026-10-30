from src.services.exceptions_service import is_exception, normalize_counterparty


def test_exception_substring_casefold():
    exceptions = ["ООО Ромашка", "ООО Гильдия Алко"]
    assert is_exception("накладная ооо ромашка №12", exceptions)
    assert is_exception("ООО Гильдия Алко, №1", exceptions)
    assert not is_exception("ИП БАТУРИН, №2744", exceptions)


def test_normalize():
    assert normalize_counterparty("  ООО   Ромашка ") == "ооо ромашка"
