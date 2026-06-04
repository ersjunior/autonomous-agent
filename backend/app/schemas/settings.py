"""Schemas for application settings API."""

from typing import Any

from pydantic import BaseModel, Field


class SettingsUpdateRequest(BaseModel):
    settings: dict[str, Any] = Field(
        ...,
        description="Map of setting key to new value (secrets: omit or send masked to keep current)",
    )


class VoiceTestRequest(BaseModel):
    text: str | None = Field(
        default=None,
        description="Texto para síntese de teste (pt-BR)",
    )


class VoiceSampleUploadResponse(BaseModel):
    filename: str
    size_bytes: int
    path: str
    message: str


class VoiceTestResponse(BaseModel):
    audio_url: str
    filename: str


class VoiceSampleInfoResponse(BaseModel):
    exists: bool
    filename: str
    size_bytes: int
    modified_at: str | None = None
    path: str = "/voices/reference.wav"


class AvatarImageUploadResponse(BaseModel):
    filename: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    message: str


class AvatarImageInfoResponse(BaseModel):
    exists: bool
    filename: str
    size_bytes: int
    modified_at: str | None = None
    width: int | None = None
    height: int | None = None


class AvatarTestRequest(BaseModel):
    text: str | None = Field(
        default=None,
        description="Texto para geração de vídeo de teste (pt-BR)",
    )


class AvatarTestResponse(BaseModel):
    video_url: str
    filename: str
