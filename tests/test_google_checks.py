from unittest.mock import MagicMock

from src.services.gmail_auth import GmailAuth, _short_err


def test_short_err_truncates():
    assert _short_err("x" * 10, limit=5) == "xxxx…"
    assert _short_err("ok", limit=10) == "ok"


def test_check_gmail_ok():
    auth = GmailAuth.__new__(GmailAuth)
    auth.auth_ok = True
    svc = MagicMock()
    svc.users.return_value.getProfile.return_value.execute.return_value = {
        "emailAddress": "theofficesakh@gmail.com"
    }
    auth.build_service = MagicMock(return_value=svc)
    ok, detail = auth.check_gmail()
    assert ok is True
    assert "theofficesakh@gmail.com" in detail


def test_check_sheets_fail():
    auth = GmailAuth.__new__(GmailAuth)
    auth.auth_ok = True
    auth.build_sheets_service = MagicMock(side_effect=RuntimeError("API off"))
    ok, detail = auth.check_sheets("sheet-id")
    assert ok is False
    assert auth.auth_ok is True  # transient API error must not kill auth flag
    assert "Sheets FAIL" in detail
    assert "API off" in detail


def test_check_gmail_auth_error_clears_flag():
    from src.services.gmail_auth import GmailAuthError

    auth = GmailAuth.__new__(GmailAuth)
    auth.auth_ok = True
    auth.build_service = MagicMock(side_effect=GmailAuthError("token dead"))
    ok, detail = auth.check_gmail()
    assert ok is False
    assert auth.auth_ok is False
    assert "token dead" in detail
