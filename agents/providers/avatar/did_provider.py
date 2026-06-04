"""D-ID commercial avatar provider — texto + URL de imagem (TTS interno)."""

import httpx

from agents.providers.base import AvatarProvider
from app.core.config import settings

DID_API_BASE = "https://api.d-id.com"


class DIDAvatarProvider(AvatarProvider):
    """Talking avatar via D-ID API (assíncrono com polling em get_video)."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))

    @property
    def provider_name(self) -> str:
        return "did"

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Basic {settings.did_api_key or ''}",
            "Content-Type": "application/json",
        }

    async def create_video(
        self,
        text: str,
        avatar_ref: str,
        audio_bytes: bytes | None = None,
    ) -> dict:
        """Inicia talk; ``audio_bytes`` é ignorado (D-ID sintetiza a partir de ``text``)."""
        response = await self._client.post(
            f"{DID_API_BASE}/talks",
            headers=self._auth_headers(),
            json={
                "source_url": avatar_ref,
                "script": {"type": "text", "input": text},
            },
        )
        response.raise_for_status()
        data = response.json()
        return {
            "id": data["id"],
            "status": data.get("status", "created"),
            "video_url": data.get("result_url"),
        }

    async def get_video(self, video_id: str) -> dict:
        response = await self._client.get(
            f"{DID_API_BASE}/talks/{video_id}",
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        data = response.json()
        result_url = data.get("result_url")
        return {
            "id": data.get("id", video_id),
            "status": data.get("status", ""),
            "video_url": result_url,
            **data,
        }

    async def aclose(self) -> None:
        await self._client.aclose()
