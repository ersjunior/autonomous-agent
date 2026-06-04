"""Application settings API (provider config with hot-reload)."""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.settings import (
    AvatarImageInfoResponse,
    AvatarImageUploadResponse,
    AvatarTestRequest,
    AvatarTestResponse,
    SettingsUpdateRequest,
    VoiceSampleInfoResponse,
    VoiceSampleUploadResponse,
    VoiceTestRequest,
    VoiceTestResponse,
)
from app.services.avatar_image import (
    avatar_image_path,
    get_avatar_image_info,
    media_type_for_path,
    save_avatar_image,
)
from app.services.avatar_video import gerar_video_avatar
from app.services.settings_service import (
    build_settings_response_payload,
    get_effective_settings,
    set_setting_internal,
    update_settings,
)
from app.services.settings_sync import ensure_settings_fresh_async
from app.services.voice_audio import gerar_audio_chamada
from app.services.voice_sample import (
    COQUI_REFERENCE_PATH,
    get_reference_wav_info,
    reference_wav_path,
    save_reference_wav,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])

DEFAULT_VOICE_TEST_TEXT = (
    "Olá! Esta é uma demonstração da minha voz personalizada, falando em português."
)

DEFAULT_AVATAR_TEST_TEXT = (
    "Olá! Esta é uma demonstração do avatar em vídeo, falando com a minha voz "
    "personalizada em português."
)


@router.get("")
async def get_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await ensure_settings_fresh_async()
    effective = await get_effective_settings(db)
    return build_settings_response_payload(effective)


@router.put("")
async def put_settings(
    payload: SettingsUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    effective = await update_settings(db, payload.settings)
    return build_settings_response_payload(effective)


@router.get("/voice-sample/info", response_model=VoiceSampleInfoResponse)
async def voice_sample_info(
    user: User = Depends(get_current_user),
) -> VoiceSampleInfoResponse:
    """Return whether reference.wav exists on the Coqui voices volume."""
    info = get_reference_wav_info()
    return VoiceSampleInfoResponse(**info)


@router.get("/voice-sample/audio")
async def voice_sample_audio(
    user: User = Depends(get_current_user),
) -> FileResponse:
    """Stream the fixed reference.wav (authenticated — use blob URL in the UI)."""
    path = reference_wav_path()
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="reference.wav não encontrado",
        )
    return FileResponse(
        path,
        media_type="audio/wav",
        filename=path.name,
    )


@router.post(
    "/voice-sample",
    response_model=VoiceSampleUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_voice_sample(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VoiceSampleUploadResponse:
    """Upload reference.wav for Coqui voice cloning (shared volume with coqui-tts)."""
    filename = file.filename or ""
    content_type = (file.content_type or "").lower()
    if content_type and not content_type.startswith("audio/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Content-Type deve ser audio/*",
        )

    raw = await file.read()
    dest, size = save_reference_wav(raw, filename)

    await update_settings(db, {"coqui_voice_sample": COQUI_REFERENCE_PATH})

    logger.info(
        "Voice sample uploaded by %s: %s (%s bytes)",
        user.email,
        dest,
        size,
    )

    return VoiceSampleUploadResponse(
        filename=dest.name,
        size_bytes=size,
        path=COQUI_REFERENCE_PATH,
        message="Amostra de voz salva com sucesso",
    )


@router.post("/voice-test", response_model=VoiceTestResponse)
async def voice_test(
    payload: VoiceTestRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VoiceTestResponse:
    """Generate test MP3 via Coqui pipeline (same as outbound calls)."""
    await ensure_settings_fresh_async()

    text = (payload.text or "").strip() or DEFAULT_VOICE_TEST_TEXT

    try:
        mp3_filename = await gerar_audio_chamada(text)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        message = str(exc)
        if "reference" in message.lower() or "speaker" in message.lower():
            detail = (
                "reference.wav ausente ou inválido. "
                "Envie uma amostra de voz antes de testar."
            )
        elif "coqui" in message.lower() or "sintetizar" in message.lower():
            detail = f"Coqui indisponível: {message}"
        else:
            detail = message
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
        ) from exc
    except Exception as exc:
        logger.exception("Voice test failed for user %s", user.email)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Falha ao gerar áudio de teste: {exc}",
        ) from exc

    audio_url = f"/api/v1/channels/webhooks/voice/audio/{mp3_filename}"
    return VoiceTestResponse(audio_url=audio_url, filename=mp3_filename)


@router.get("/avatar-image/info", response_model=AvatarImageInfoResponse)
async def avatar_image_info(
    user: User = Depends(get_current_user),
) -> AvatarImageInfoResponse:
    """Metadata for the current avatar face image in avatars_root."""
    await ensure_settings_fresh_async()
    info = get_avatar_image_info()
    return AvatarImageInfoResponse(**info)


@router.get("/avatar-image/preview")
async def avatar_image_preview(
    user: User = Depends(get_current_user),
) -> FileResponse:
    """Stream the configured avatar face image (authenticated preview in UI)."""
    await ensure_settings_fresh_async()
    path = avatar_image_path()
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Imagem de avatar não encontrada",
        )
    return FileResponse(
        path,
        media_type=media_type_for_path(path),
        filename=path.name,
    )


@router.post(
    "/avatar-image",
    response_model=AvatarImageUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_avatar_image(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AvatarImageUploadResponse:
    """Upload face image for SadTalker (shared avatars volume)."""
    filename = file.filename or ""
    content_type = (file.content_type or "").lower()
    raw = await file.read()
    dest, size, width, height = save_avatar_image(raw, filename, content_type)

    await set_setting_internal(db, "avatar_default_image", dest.name)

    logger.info(
        "Avatar image uploaded by %s: %s (%s bytes)",
        user.email,
        dest,
        size,
    )

    return AvatarImageUploadResponse(
        filename=dest.name,
        size_bytes=size,
        width=width,
        height=height,
        message="Imagem do avatar salva com sucesso",
    )


@router.post("/avatar-test", response_model=AvatarTestResponse)
async def avatar_test(
    payload: AvatarTestRequest,
    user: User = Depends(get_current_user),
) -> AvatarTestResponse:
    """Generate test MP4 via Coqui + SadTalker (same pipeline as outbound video)."""
    await ensure_settings_fresh_async()

    text = (payload.text or "").strip() or DEFAULT_AVATAR_TEST_TEXT

    try:
        mp4_filename = await gerar_video_avatar(text)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        message = str(exc)
        if "não encontrada" in message.lower() or "avatar" in message.lower():
            detail = (
                "Imagem de avatar ausente. Envie uma foto de rosto antes de testar."
            )
        elif "sadtalker" in message.lower() or "coqui" in message.lower():
            detail = message
        else:
            detail = message
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
        ) from exc
    except Exception as exc:
        logger.exception("Avatar test failed for user %s", user.email)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Falha ao gerar vídeo de teste: {exc}",
        ) from exc

    video_url = f"/api/v1/channels/avatar-video/{mp4_filename}"
    return AvatarTestResponse(video_url=video_url, filename=mp4_filename)
