"""D-ID commercial avatar provider."""

import httpx

from agents.providers.base import AvatarProvider
from app.core.config import settings

DID_API_BASE = "https://api.d-id.com"


class DIDAvatarProvider(AvatarProvider):
    """Talking avatar via D-ID API."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))

    @property
    def provider_name(self) -> str:
        return "did"

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Basic {settings.did_api_key or ''}",
            "Content-Type": "application/json",
        }

    async def create_video(self, text: str, avatar_id: str) -> dict:
        response = await self._client.post(
            f"{DID_API_BASE}/talks",
            headers=self._auth_headers(),
            json={
                "source_url": avatar_id,
                "script": {"type": "text", "input": text},
            },
        )
        response.raise_for_status()
        data = response.json()
        return {"id": data["id"], "status": data["status"]}

    async def get_video(self, video_id: str) -> dict:
        response = await self._client.get(
            f"{DID_API_BASE}/talks/{video_id}",
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def aclose(self) -> None:
        await self._client.aclose()
