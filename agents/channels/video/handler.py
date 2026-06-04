"""Video channel handler."""

from agents.channels.voice.tts_stt import text_to_speech
from agents.orchestrator.router import route_message
from agents.provider_factory import ProviderFactory


class VideoHandler:
    async def handle_video_call(
        self,
        message: str,
        user_id: str,
        avatar_ref: str,
    ) -> str:
        result = await route_message(message, "video", user_id)
        response_text = result.get("response", "")

        audio_bytes = await text_to_speech(response_text)

        avatar = ProviderFactory.get_avatar()
        talk = await avatar.create_video(
            response_text,
            avatar_ref,
            audio_bytes=audio_bytes,
        )
        return talk.get("video_filename") or talk.get("id", "")
