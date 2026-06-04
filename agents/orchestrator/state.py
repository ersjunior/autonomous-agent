"""Shared graph state definition."""

from typing import NotRequired, TypedDict


class AgentState(TypedDict):
    message: str
    channel: str
    user_id: str
    intent: str
    confidence: float
    entities: dict
    response: str
    should_escalate: bool
    conversation_history: list[dict]
    rag_memories: NotRequired[list[dict]]
    agent_id: NotRequired[str]
    agent_name: NotRequired[str]
    agent_mode: NotRequired[str]
    agent_personality: NotRequired[str]
