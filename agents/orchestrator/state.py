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
    kb_chunks: NotRequired[list[dict]]
    owner_user_id: NotRequired[str | None]
    complaint_severity: NotRequired[str]
    agent_id: NotRequired[str]
    agent_name: NotRequired[str]
    agent_mode: NotRequired[str]
    agent_personality: NotRequired[str]
    intent_ms: NotRequired[float]
    rag_ms: NotRequired[float]
    response_ms: NotRequired[float]
