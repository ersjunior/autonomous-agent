"""Voice channel handler."""

from agents.channels.voice.tts_stt import speech_to_text, text_to_speech
from agents.orchestrator.graph import AgentState, agent_graph


class VoiceHandler:
    async def handle_call(self, audio_bytes: bytes, user_id: str) -> bytes:
        message = await speech_to_text(audio_bytes)

        initial_state: AgentState = {
            "message": message,
            "channel": "voice",
            "user_id": user_id,
            "intent": "",
            "confidence": 0.0,
            "entities": {},
            "response": "",
            "should_escalate": False,
            "conversation_history": [],
        }

        result = await agent_graph.ainvoke(initial_state)
        response_text = result.get("response", "")
        return await text_to_speech(response_text)
