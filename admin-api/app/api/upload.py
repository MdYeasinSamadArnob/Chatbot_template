"""
Image upload endpoint.

POST /api/upload
    Accepts a single image file, validates its content via magic bytes
    (never trusts client-provided filename or MIME type), enforces a
    configurable size limit, saves it under YYYY/MM/<uuid>.<ext>, and
    returns the public-accessible URL path.

WARNING: Uploaded files are served as static files and are publicly
accessible to anyone who knows the URL.  Do NOT upload sensitive content.

Auth: x-admin-secret header required.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["upload"])

# ── Magic-byte table ──────────────────────────────────────────────────────
# Extension is always derived from file content — never from the filename.
_MAGIC: list[tuple[bytes, bytes, str]] = [
    # (prefix_to_match, mask_or_empty, extension)
    (b"\xff\xd8\xff", b"", "jpg"),
    (b"\x89PNG\r\n\x1a\n", b"", "png"),
    (b"GIF87a", b"", "gif"),
    (b"GIF89a", b"", "gif"),
    (b"RIFF", b"WEBP", "webp"),  # RIFF????WEBP — checked separately below
]

_MAX_HEADER_BYTES = 12


def _detect_ext(header: bytes) -> str | None:
    """Return file extension from magic bytes, or None if not a known image."""
    for magic, extra, ext in _MAGIC:
        if not header.startswith(magic):
            continue
        if extra:
            # WEBP: bytes 8-11 must be the extra signature
            if header[8:12] == extra:
                return ext
            continue
        return ext
    return None


# ── Auth dependency ───────────────────────────────────────────────────────

async def require_admin(x_admin_secret: str = Header(default="")) -> None:
    if not settings.admin_secret or x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Invalid or missing admin secret")


# ── Upload endpoint ───────────────────────────────────────────────────────

@router.post("/upload", dependencies=[Depends(require_admin)])
async def upload_image(file: UploadFile) -> dict:
    """
    Upload an image file.

    - Validates content via magic bytes (extension derived from content, not filename).
    - Rejects files larger than `upload_max_mb` MB.
    - Saves to `uploads_dir/YYYY/MM/<uuid>.<ext>`.
    - Returns `{"url": "/uploads/YYYY/MM/<filename>", "filename": "<filename>"}`.
    """
    max_bytes = settings.upload_max_mb * 1024 * 1024

    # ── Read header for magic-byte validation ─────────────────────────
    header = await file.read(_MAX_HEADER_BYTES)
    if len(header) < 4:
        raise HTTPException(status_code=400, detail="File is too small to be a valid image")

    ext = _detect_ext(header)
    if ext is None:
        raise HTTPException(
            status_code=400,
            detail="Only image files are allowed (JPEG, PNG, GIF, WEBP)",
        )

    # ── Stream the remainder, enforcing size limit ────────────────────
    body = header
    chunk_size = 64 * 1024  # 64 KB chunks
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        body += chunk
        if len(body) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds {settings.upload_max_mb} MB limit",
            )

    # ── Build date-based output path ──────────────────────────────────
    now = datetime.now(timezone.utc)
    subdir = os.path.join(settings.uploads_dir, str(now.year), f"{now.month:02d}")
    os.makedirs(subdir, exist_ok=True)

    filename = f"{uuid.uuid4().hex}.{ext}"
    dest = os.path.join(subdir, filename)

    with open(dest, "wb") as f:
        f.write(body)

    rel_url = f"/uploads/{now.year}/{now.month:02d}/{filename}"
    size_kb = round(len(body) / 1024, 1)
    logger.info(
        "upload: ext=%s size_kb=%s path=%s original_name=%s",
        ext, size_kb, dest, file.filename or "(none)",
    )

    return {"url": rel_url, "filename": filename}
