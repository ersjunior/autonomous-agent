"""Voice channel handler.

Outbound PSTN: ver ``twilio_voice_client`` + webhook ``/webhooks/voice/outbound``.

Fase 2 (inbound): ``handle_call`` + Twilio Media Streams (STT/TTS bidirecional) — não implementado.
"""

from agents.channels.voice.tts_stt import speech_to_text, text_to_speech
from agents.orchestrator.router import route_message


class VoiceHandler:
    async def handle_call(self, audio_bytes: bytes, user_id: str) -> bytes:
        """Fase 2: áudio inbound via Media Streams → STT → agente → TTS."""
        message = await speech_to_text(audio_bytes)
        result = await route_message(message, "voice", user_id)
        response_text = result.get("response", "")
        return await text_to_speech(response_text)
