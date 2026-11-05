"""Safe image intake for avatars.

Uploads are untrusted: size is capped before decoding, the real format is detected from the
file bytes (the browser-supplied MIME type is ignored), decoding is verified, decompression
bombs are rejected, EXIF/metadata is dropped and the result is re-encoded as a small PNG.
Only the re-encoded bytes are stored or served.
"""
from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 24_000_000
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP"}


class ImageError(ValueError):
    """Message is safe to show to the user."""


def process_image(raw: bytes, *, max_bytes: int, size: tuple[int, int], square: bool = True) -> bytes:
    if not raw:
        raise ImageError("No image data received.")
    if len(raw) > max_bytes:
        raise ImageError(f"Image must be under {max_bytes // 1024} KB.")
    try:
        probe = Image.open(io.BytesIO(raw))
        if probe.format not in ALLOWED_FORMATS:
            raise ImageError("Only PNG, JPEG, or WebP images are allowed.")
        probe.verify()
        img = Image.open(io.BytesIO(raw))
        img.load()
    except ImageError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        raise ImageError("That file is not a valid image.") from None
    img = ImageOps.exif_transpose(img).convert("RGBA")
    img = ImageOps.fit(img, size, method=Image.LANCZOS) if square else img
    if not square:
        img.thumbnail(size, Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)     # fresh encode: no metadata, no trailing data
    return out.getvalue()
