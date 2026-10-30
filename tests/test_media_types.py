from src.services.media_types import is_allowed_media


def test_allowed_types():
    assert is_allowed_media("a.jpg", "image/jpeg")
    assert is_allowed_media("a.HEIC", "image/heic")
    assert is_allowed_media("a.png", None)
    assert is_allowed_media("a.pdf", "application/pdf")
    assert is_allowed_media("scan.PDF", None)
    assert not is_allowed_media("doc.docx", "application/vnd.openxmlformats")
