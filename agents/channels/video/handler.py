"""Video channel handler."""

from agents.channels.video.avatar_client import DIDClient
from agents.orchestrator.router import route_message


class VideoHandler:
    async def handle_video_call(
        self, message: str, user_id: str, avatar_id: str
    ) -> str:
        result = await route_message(message, "video", user_id)
        response_text = result.get("response", "")

        talk = await DIDClient().create_talk(response_text, avatar_id)
        return talk["id"]
