from pathlib import Path

from src.parsers.docsinbox import IncomingKind, parse_incoming_email

FIXTURES = Path(__file__).resolve().parents[1] / "docs" / "email-examples"


def _body_from_md(name: str) -> str:
    text = (FIXTURES / name).read_text(encoding="utf-8")
    start = text.index("```\n") + 4
    end = text.index("\n```", start)
    return text[start:end]


def test_parse_appeal_email():
    body = _body_from_md("01-received-by-system.md")
    parsed = parse_incoming_email(
        subject="ООО Сфофрендз инн 6501291591\\ ИП БАТУРИН, №2744",
        body=body,
    )
    assert parsed.kind == IncomingKind.APPEAL
    assert parsed.appeal_number == "059137937"


def test_parse_entered_email():
    body = _body_from_md("02-entered-into-system.md")
    parsed = parse_incoming_email(
        subject="ООО Сфофрендз инн 6501291591\\ ИП БАТУРИН, №2744",
        body=body,
    )
    assert parsed.kind == IncomingKind.ENTERED
    assert parsed.appeal_number is None
    assert len(parsed.documents) >= 1
    assert parsed.documents[0].sp_number == "СП0000000081984"
    assert "dxbx.ru" in parsed.documents[0].url
    assert parsed.documents[0].dxbx_id == "79448515"


def test_parse_already_in_system_email():
    body = _body_from_md("03-already-in-system.md")
    parsed = parse_incoming_email(
        subject="ООО Сфофрендз инн 6501291591\\ ИП БАТУРИН, №2744",
        body=body,
    )
    assert parsed.kind == IncomingKind.ENTERED
    assert parsed.appeal_number is None
    assert len(parsed.documents) == 1
    assert parsed.documents[0].sp_number == "56241"
    assert parsed.documents[0].date == "12.10.2026"
    assert parsed.documents[0].dxbx_id == "79448310"
    assert "79448310" in parsed.documents[0].url
