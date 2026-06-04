"""Persist avatar face image on shared avatars volume."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from app.core.config import settings

ALLOWED_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg"})
ALLOWED_CONTENT_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/jpg", "application/octet-stream"}
)
MAX_AVATAR_IMAGE_BYTES = 10 * 1024 * 1024
MIN_IMAGE_WIDTH = 256
MIN_IMAGE_HEIGHT = 256
AVATAR_SAVE_BASENAME = "avatar"


def _extension_from_filename(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".jpeg":
        return ".jpg"
    if ext in ALLOWED_EXTENSIONS:
        return ext if ext != ".jpeg" else ".jpg"
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Extensão inválida. Use .png, .jpg ou .jpeg",
    )


def _validate_image_content(content: bytes, filename: str, content_type: str) -> tuple[int | None, int | None]:
    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Arquivo vazio",
        )

    if len(content) > MAX_AVATAR_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Arquivo excede o limite de {MAX_AVATAR_IMAGE_BYTES // (1024 * 1024)}MB",
        )

    ext = _extension_from_filename(filename)
    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
        if not content_type.startswith("image/"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Content-Type deve ser image/*",
            )

    width: int | None = None
    height: int | None = None
    try:
        from PIL import Image

        with Image.open(io.BytesIO(content)) as img:
            width, height = img.size
            if width < MIN_IMAGE_WIDTH or height < MIN_IMAGE_HEIGHT:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Imagem muito pequena ({width}x{height}). "
                        f"Mínimo: {MIN_IMAGE_WIDTH}x{MIN_IMAGE_HEIGHT}px"
                    ),
                )
    except HTTPException:
        raise
    except ImportError:
        pass
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Imagem inválida: {exc}",
        ) from exc

    return width, height


def avatar_image_path() -> Path:
    """Current avatar face file — basename from settings only (no user path)."""
    name = Path((settings.avatar_default_image or "default.png").strip()).name
    if not name or name in (".", ".."):
        name = "default.png"
    return Path(settings.avatars_root) / name


def media_type_for_path(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    return "application/octet-stream"


def get_avatar_image_info() -> dict[str, Any]:
    path = avatar_image_path()
    filename = path.name
    if not path.is_file():
        return {
            "exists": False,
            "filename": filename,
            "size_bytes": 0,
            "modified_at": None,
            "width": None,
            "height": None,
        }

    stat = path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    width: int | None = None
    height: int | None = None
    try:
        from PIL import Image

        with Image.open(path) as img:
            width, height = img.size
    except Exception:
        pass

    return {
        "exists": True,
        "filename": filename,
        "size_bytes": stat.st_size,
        "modified_at": modified_at,
        "width": width,
        "height": height,
    }


def save_avatar_image(content: bytes, filename: str, content_type: str) -> tuple[Path, int, str | None, str | None]:
    """Write face image to avatars volume; returns path, size, width, height."""
    width, height = _validate_image_content(content, filename, content_type)
    ext = _extension_from_filename(filename)
    dest_name = f"{AVATAR_SAVE_BASENAME}{ext}"

    root = Path(settings.avatars_root)
    root.mkdir(parents=True, exist_ok=True)
    dest = root / dest_name
    dest.write_bytes(content)

    return dest, len(content), width, height
