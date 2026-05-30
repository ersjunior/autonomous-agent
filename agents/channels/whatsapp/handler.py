"""WhatsApp webhook handler wired to the LangGraph orchestrator."""

import xml.sax.saxutils

from agents.orchestrator.graph import AgentState, agent_graph


class WhatsAppHandler:
    async def handle_webhook(self, payload: dict) -> str:
        body = payload.get("Body", "")
        from_number = payload.get("From", "")

        if not body or not from_number:
            return "<Response></Response>"

        initial_state: AgentState = {
            "message": body,
            "channel": "whatsapp",
            "user_id": from_number,
            "intent": "",
            "confidence": 0.0,
            "entities": {},
            "response": "",
            "should_escalate": False,
            "conversation_history": [],
        }

        result = await agent_graph.ainvoke(initial_state)
        response_text = result.get("response", "")
        escaped = xml.sax.saxutils.escape(response_text)
        return f"<Response><Message>{escaped}</Message></Response>"
