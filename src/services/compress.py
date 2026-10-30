from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:  # noqa: BLE001
    logger.warning("pillow-heif not available; HEIC may fail")


RESIZE_STEPS = (2560, 1920, 1600, 1280)
QUALITY_STEPS = (85, 70, 55)


def total_size(paths: list[Path]) -> int:
    return sum(p.stat().st_size for p in paths if p.exists())


def compress_images_to_limit(paths: list[Path], max_bytes: int) -> tuple[list[Path], bool]:
    """Return paths to send and whether compression was applied."""
    if total_size(paths) <= max_bytes:
        return paths, False

    out_paths: list[Path] = []
    for path in paths:
        out_paths.append(_compress_one(path))

    if total_size(out_paths) <= max_bytes:
        return out_paths, True

    # Progressive harder compress
    for max_side in RESIZE_STEPS:
        for quality in QUALITY_STEPS:
            hardened: list[Path] = []
            for path in paths:
                hardened.append(_compress_one(path, max_side=max_side, quality=quality))
            if total_size(hardened) <= max_bytes:
                return hardened, True
            out_paths = hardened

    return out_paths, True


def _compress_one(
    path: Path, *, max_side: int = 2560, quality: int = 85
) -> Path:
    out = path.with_name(f"{path.stem}_c.jpg")
    with Image.open(path) as img:
        img = img.convert("RGB")
        width, height = img.size
        longest = max(width, height)
        if longest > max_side:
            scale = max_side / longest
            img = img.resize(
                (max(1, int(width * scale)), max(1, int(height * scale))),
                Image.Resampling.LANCZOS,
            )
        img.save(out, format="JPEG", quality=quality, optimize=True)
    return out
