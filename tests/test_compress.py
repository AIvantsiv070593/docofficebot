from pathlib import Path

from PIL import Image

from src.services.compress import compress_images_to_limit, total_size


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
