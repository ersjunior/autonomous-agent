"""Video channel handler."""

from agents.orchestrator.router import route_message
from agents.provider_factory import ProviderFactory


class VideoHandler:
    async def handle_video_call(
        self, message: str, user_id: str, avatar_id: str
    ) -> str:
        result = await route_message(message, "video", user_id)
        response_text = result.get("response", "")

        avatar = ProviderFactory.get_avatar()
        talk = await avatar.create_video(response_text, avatar_id)
        return talk["id"]
