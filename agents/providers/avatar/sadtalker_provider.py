"""SadTalker local avatar provider."""

import httpx

from agents.providers.base import AvatarProvider
from app.core.config import settings


class SadTalkerAvatarProvider(AvatarProvider):
    """Talking avatar via local SadTalker REST service."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.sadtalker_base_url.rstrip("/"),
            timeout=httpx.Timeout(300.0),
        )

    @property
    def provider_name(self) -> str:
        return "sadtalker"

    async def create_video(self, text: str, avatar_id: str) -> dict:
        response = await self._client.post(
            "/videos",
            json={"text": text, "avatar_id": avatar_id},
        )
        response.raise_for_status()
        data = response.json()
        return {
            "id": data.get("id", data.get("video_id", "")),
            "status": data.get("status", "created"),
        }

    async def get_video(self, video_id: str) -> dict:
        response = await self._client.get(f"/videos/{video_id}")
        response.raise_for_status()
        return response.json()

    async def aclose(self) -> None:
        await self._client.aclose()
