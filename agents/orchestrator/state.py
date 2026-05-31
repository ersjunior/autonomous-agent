"""Shared graph state definition."""

from typing import TypedDict


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
