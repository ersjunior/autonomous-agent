"""Video channel handler."""

from agents.channels.video.avatar_client import DIDClient
from agents.orchestrator.graph import AgentState, agent_graph


class VideoHandler:
    async def handle_video_call(
        self, message: str, user_id: str, avatar_id: str
    ) -> str:
        initial_state: AgentState = {
            "message": message,
            "channel": "video",
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

        talk = await DIDClient().create_talk(response_text, avatar_id)
        return talk["id"]
