"""Central dispatcher — routes messages from channels to the LangGraph orchestrator."""

from __future__ import annotations

from agents.events import publish_event_async
from agents.orchestrator.state import AgentState

VALID_CHANNELS = frozenset({"telegram", "whatsapp", "voice", "video"})


def build_initial_state(
    message: str,
    channel: str,
    user_id: str,
    *,
    agent_context: dict | None = None,
) -> AgentState:
    """Build a complete AgentState for graph invocation."""
    normalized_channel = channel.lower()
    if normalized_channel not in VALID_CHANNELS:
        raise ValueError(f"Unsupported channel: {channel}")

    state: AgentState = {
        "message": message,
        "channel": normalized_channel,
        "user_id": user_id,
        "intent": "",
        "confidence": 0.0,
        "entities": {},
        "response": "",
        "should_escalate": False,
        "conversation_history": [],
    }
    if agent_context:
        state.update(agent_context)
    return state


def route_after_escalation_check(state: AgentState) -> str:
    """Conditional edge: escalate to human or generate an automated response."""
    if state.get("should_escalate"):
        return "escalate"
    return "generate_response"


async def route_message(
    message: str,
    channel: str,
    user_id: str,
    *,
    notify_received: bool = False,
    agent_context: dict | None = None,
) -> AgentState:
    """Run a message through the agent graph and return the final state."""
    from app.services.settings_sync import ensure_settings_fresh_async

    await ensure_settings_fresh_async()

    from agents.orchestrator.graph import agent_graph

    normalized_channel = channel.lower()
    if notify_received:
        await publish_event_async(
            "message_received",
            {
                "channel": normalized_channel,
                "user_id": user_id,
                "message": message,
            },
        )

    state = build_initial_state(
        message,
        normalized_channel,
        user_id,
        agent_context=agent_context,
    )
    return await agent_graph.ainvoke(state)


async def get_response(
    message: str,
    channel: str,
    user_id: str,
    *,
    notify_received: bool = False,
) -> str:
    """Convenience wrapper — returns only the response text."""
    result = await route_message(
        message,
        channel,
        user_id,
        notify_received=notify_received,
    )
    return result.get("response", "")
