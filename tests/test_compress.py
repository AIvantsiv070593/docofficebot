from pathlib import Path

import fitz
from PIL import Image

from src.services.compress import (
    compress_attachments_to_limit,
    compress_images_to_limit,
    total_size,
)


def test_compress_reduces_below_limit(tmp_path: Path):
    big = tmp_path / "big.jpg"
    img = Image.new("RGB", (4000, 3000), color=(120, 40, 40))
    img.save(big, quality=95)
    assert big.stat().st_size > 50_000

    out, compressed = compress_images_to_limit([big], max_bytes=80_000)
    assert compressed is True
    assert total_size(out) <= 80_000
    assert out[0].exists()


def test_no_compress_when_small(tmp_path: Path):
    small = tmp_path / "small.jpg"
    Image.new("RGB", (64, 64), color=(10, 10, 10)).save(small, quality=50)
    out, compressed = compress_images_to_limit([small], max_bytes=20 * 1024 * 1024)
    assert compressed is False
    assert out == [small]


def _pdf_with_big_image(tmp_path: Path) -> Path:
    img = tmp_path / "page.jpg"
    Image.new("RGB", (2500, 2500), (200, 80, 40)).save(img, quality=95)
    pdf = tmp_path / "scan.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, filename=str(img))
    doc.save(pdf)
    doc.close()
    return pdf


def test_small_pdf_unchanged(tmp_path: Path):
    pdf = tmp_path / "tiny.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "ok")
    doc.save(pdf)
    doc.close()
    out, compressed = compress_attachments_to_limit([pdf], max_bytes=20 * 1024 * 1024)
    assert compressed is False
    assert out == [pdf]


def test_large_pdf_compressed_below_limit(tmp_path: Path):
    pdf = _pdf_with_big_image(tmp_path)
    limit = max(30_000, pdf.stat().st_size // 4)
    assert pdf.stat().st_size > limit
    out, compressed = compress_attachments_to_limit([pdf], max_bytes=limit)
    assert compressed is True
    assert total_size(out) <= limit
    assert all(p.exists() for p in out)
