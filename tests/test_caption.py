from src.services.caption import (
    build_outgoing_subject,
    clean_claim_caption,
    has_send_command,
)


class _Msg:
    def __init__(self, caption="", text="", caption_entities=None, entities=None):
        self.caption = caption
        self.text = text
        self.caption_entities = caption_entities
        self.entities = entities


def test_clean_strips_send_and_mention():
    assert (
        clean_claim_caption("/send ИП БАТУРИН, №2744") == "ИП БАТУРИН, №2744"
    )
    assert (
        clean_claim_caption("/send@office_sakh_bot ИП БАТУРИН, №2744")
        == "ИП БАТУРИН, №2744"
    )
    assert clean_claim_caption("@bot ИП БАТУРИН") == "ИП БАТУРИН"


def test_has_send_command():
    assert has_send_command(_Msg(caption="/send ООО Ромашка №1"))
    assert has_send_command(_Msg(caption="/send@office_sakh_bot test"))
    assert not has_send_command(_Msg(caption="ООО Ромашка №1"))
    assert not has_send_command(_Msg(caption="@office_sakh_bot ООО"))


def test_subject_format():
    subject = build_outgoing_subject(
        "ООО Сфофрендз инн 6501291591",
        "ИП БАТУРИН, №2744",
    )
    assert subject == "ООО Сфофрендз инн 6501291591\\ ИП БАТУРИН, №2744"
