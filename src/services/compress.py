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

try:
    import fitz  # PyMuPDF
except Exception:  # noqa: BLE001
    fitz = None  # type: ignore[assignment]
    logger.warning("pymupdf not available; PDF compress may fail")


RESIZE_STEPS = (2560, 1920, 1600, 1280)
QUALITY_STEPS = (85, 70, 55)


def total_size(paths: list[Path]) -> int:
    return sum(p.stat().st_size for p in paths if p.exists())


def compress_attachments_to_limit(
    paths: list[Path], max_bytes: int
) -> tuple[list[Path], bool]:
    """Shrink images/PDFs until total size fits max_bytes (or best effort)."""
    if total_size(paths) <= max_bytes:
        return paths, False

    did = False
    current: list[Path] = []
    for path in paths:
        if path.suffix.casefold() == ".pdf":
            rewritten = _pdf_rewrite(path)
            current.append(rewritten)
            did = did or rewritten != path
        else:
            current.append(path)

    if total_size(current) <= max_bytes:
        return current, did

    # Still too big: turn PDFs into JPEGs, then reuse image compressor.
    flat: list[Path] = []
    for path in current:
        if path.suffix.casefold() == ".pdf":
            pages = _pdf_to_jpegs(path, dpi=120, quality=70)
            flat.extend(pages)
            did = True
        else:
            flat.append(path)

    if total_size(flat) <= max_bytes:
        return flat, did

    outs, img_did = compress_images_to_limit(flat, max_bytes)
    return outs, did or img_did


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


def _pdf_rewrite(path: Path) -> Path:
    if fitz is None:
        return path
    out = path.with_name(f"{path.stem}_c.pdf")
    doc = fitz.open(path)
    try:
        doc.save(out, garbage=4, deflate=True, clean=True)
    finally:
        doc.close()
    return out if out.exists() else path


def _pdf_to_jpegs(path: Path, *, dpi: int, quality: int) -> list[Path]:
    if fitz is None:
        raise RuntimeError("pymupdf required to compress oversized PDF")
    doc = fitz.open(path)
    out: list[Path] = []
    try:
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=mat)
            dest = path.with_name(f"{path.stem}_p{i}_c.jpg")
            pix.save(dest, jpg_quality=quality)
            out.append(dest)
    finally:
        doc.close()
    if not out:
        raise RuntimeError(f"PDF has no pages: {path.name}")
    return out
