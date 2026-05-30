"""Avatar client (D-ID)."""

import httpx

from app.core.config import settings

DID_API_BASE = "https://api.d-id.com"


class DIDClient:
    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Basic {settings.did_api_key or ''}",
            "Content-Type": "application/json",
        }

    async def create_talk(self, text: str, avatar_id: str) -> dict:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{DID_API_BASE}/talks",
                headers=self._auth_headers(),
                json={
                    "source_url": avatar_id,
                    "script": {
                        "type": "text",
                        "input": text,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()
            return {"id": data["id"], "status": data["status"]}

    async def get_talk(self, talk_id: str) -> dict:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{DID_API_BASE}/talks/{talk_id}",
                headers=self._auth_headers(),
            )
            response.raise_for_status()
            return response.json()
