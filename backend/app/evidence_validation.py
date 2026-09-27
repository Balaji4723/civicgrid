"""Upload validation: decide what a file REALLY is from its bytes, never from its name or the client's Content-Type.

Pure functions (no DB, no HTTP) so they can be tested exhaustively.

Supported: JPEG, PNG, WebP (images, additionally decoded with Pillow) and MP4 / QuickTime / WebM (video,
validated by container signature only - see README limitations). Everything else is refused, including
documents, archives, scripts, SVG and executables.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import BinaryIO, Optional

from .errors import ServiceError

HEAD_BYTES = 64


@dataclass(frozen=True)
class Detected:
    media_type: str
    kind: str                      # "IMAGE" | "VIDEO"
    extensions: tuple[str, ...]


JPEG = Detected("image/jpeg", "IMAGE", (".jpg", ".jpeg"))
PNG = Detected("image/png", "IMAGE", (".png",))
WEBP = Detected("image/webp", "IMAGE", (".webp",))
MP4 = Detected("video/mp4", "VIDEO", (".mp4", ".m4v"))
MOV = Detected("video/quicktime", "VIDEO", (".mov",))
WEBM = Detected("video/webm", "VIDEO", (".webm",))

_MP4_BRANDS = {b"isom", b"iso2", b"iso3", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1", b"dash", b"M4V ", b"M4VH", b"M4VP"}

# Recognisable dangerous content, so the error can say WHY (everything not whitelisted is refused anyway).
_DANGEROUS = [
    (b"MZ", "a Windows executable"), (b"\x7fELF", "a Linux executable"), (b"#!", "a script"),
    (b"PK\x03\x04", "a zip/Office/JAR/APK archive"), (b"%PDF", "a PDF document"),
    (b"<?php", "PHP code"), (b"<html", "an HTML page"), (b"<!doc", "an HTML page"), (b"<svg", "an SVG (scriptable) image"),
    (b"<?xml", "XML/SVG content"), (b"\xca\xfe\xba\xbe", "a Java class / Mach-O binary"),
]
DANGEROUS_EXTENSIONS = {
    "exe", "dll", "com", "bat", "cmd", "msi", "scr", "ps1", "vbs", "js", "mjs", "jar", "sh", "bash", "py", "pl", "rb",
    "php", "phtml", "asp", "aspx", "jsp", "html", "htm", "svg", "xml", "apk", "app", "bin", "so", "dmg", "iso", "lnk", "hta",
}


def sniff(head: bytes) -> Optional[Detected]:
    """Identify by magic bytes. Returns None when the content is not one of the supported types."""
    if head.startswith(b"\xff\xd8\xff"):
        return JPEG
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return WEBP
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand == b"qt  ":
            return MOV
        if brand in _MP4_BRANDS:
            return MP4
        return None            # HEIC/AVIF/3GP etc: same box format, not supported
    if head.startswith(b"\x1a\x45\xdf\xa3") and b"webm" in head[:HEAD_BYTES]:
        return WEBM
    return None


def describe_rejected(head: bytes) -> str:
    low = head.lower()
    for sig, what in _DANGEROUS:
        if head.startswith(sig) or low.startswith(sig.lower()):
            return what
    return "an unsupported or unrecognised format"


def safe_filename(name: Optional[str]) -> str:
    """Display-only name: no path, no control chars, bounded length. Never used to build a storage path."""
    if not name or "\x00" in name:
        raise ServiceError(422, "BAD_FILENAME", "The upload needs a file name.")
    base = os.path.basename(name.replace("\\", "/")).strip()
    base = re.sub(r"[^\w.\- ]", "_", base, flags=re.UNICODE)
    base = re.sub(r"\.{2,}", ".", base).strip(" .")
    if not base or base.startswith("."):
        raise ServiceError(422, "BAD_FILENAME", "That file name is not usable.")
    parts = base.lower().split(".")[1:]
    bad = [p for p in parts if p in DANGEROUS_EXTENSIONS]
    if bad:
        raise ServiceError(415, "UNSAFE_FILENAME",
                           f"File names containing '.{bad[0]}' are refused (double extensions are a common upload trick). Rename the file.")
    return base[:120]


def check_type_consistency(det: Detected, filename: str, declared_content_type: Optional[str]) -> None:
    """The bytes decide. The extension and any declared Content-Type must agree with them."""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in det.extensions:
        raise ServiceError(415, "EXTENSION_CONTENT_MISMATCH",
                           f"The file content is {det.media_type} but the name ends in '{ext or '(no extension)'}' "
                           f"(expected one of {', '.join(det.extensions)}). Renamed files are refused.")
    ct = (declared_content_type or "").split(";")[0].strip().lower()
    if ct and ct != "application/octet-stream" and ct != det.media_type:
        raise ServiceError(415, "CONTENT_TYPE_MISMATCH",
                           f"The upload was declared as {ct} but its content is {det.media_type}.")


def verify_image(fp: BinaryIO, max_pixels: int) -> tuple[int, int]:
    """Fully parse the image with Pillow: refuses truncated/corrupt files and decompression bombs."""
    from PIL import Image, UnidentifiedImageError
    Image.MAX_IMAGE_PIXELS = max_pixels
    fp.seek(0)
    try:
        with Image.open(fp) as im:
            w, h = im.size
            if w * h > max_pixels:
                raise ServiceError(413, "IMAGE_TOO_LARGE", f"Image has {w * h:,} pixels; the limit is {max_pixels:,}.")
            im.verify()
        fp.seek(0)
        with Image.open(fp) as im2:   # verify() does not decode pixel data; decode once to catch truncation
            im2.load()
        return w, h
    except ServiceError:
        raise
    except Image.DecompressionBombError as e:
        raise ServiceError(413, "IMAGE_TOO_LARGE", "Image dimensions are implausibly large.") from e
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as e:
        raise ServiceError(422, "CORRUPT_IMAGE", "The image is corrupt or truncated and cannot be decoded.") from e
    finally:
        fp.seek(0)
