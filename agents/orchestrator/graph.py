"""LangGraph orchestrator for customer service conversations."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from agents.events import publish_event_async
from agents.memory.long_term import LongTermMemory
from agents.memory.short_term import ShortTermMemory
from agents.workers.intent_agent import identify_intent as run_identify_intent
from agents.workers.response_agent import generate_response as run_generate_response

ESCALATION_CONFIDENCE_THRESHOLD = 0.5

_short_term_memory = ShortTermMemory()
_long_term_memory = LongTermMemory()


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


async def identify_intent(state: AgentState) -> AgentState:
    memory = _short_term_memory
    history = await memory.get_history(state["user_id"])
    result = await run_identify_intent(
        state["message"],
        history,
    )
    await publish_event_async(
        "intent_detected",
        {
            "user_id": state["user_id"],
            "channel": state.get("channel", ""),
            "message": state["message"],
            "intent": result.intent,
            "confidence": result.confidence,
        },
    )
    return {
        "intent": result.intent,
        "confidence": result.confidence,
        "entities": result.entities,
        "conversation_history": history,
    }


async def check_escalation(state: AgentState) -> AgentState:
    intent = state.get("intent", "")
    confidence = state.get("confidence", 1.0)
    should_escalate = intent == "escalate" or confidence < ESCALATION_CONFIDENCE_THRESHOLD
    return {"should_escalate": should_escalate}


async def escalate(state: AgentState) -> AgentState:
    return {
        "response": (
            "Entendi. Vou encaminhar você para um atendente humano. "
            "Por favor, aguarde um momento."
        ),
        "should_escalate": True,
    }


async def generate_response(state: AgentState) -> AgentState:
    text = await run_generate_response(
        state.get("intent", "other"),
        state.get("entities", {}),
        state.get("conversation_history", []),
        state.get("channel", ""),
    )
    return {"response": text}


async def send_response(state: AgentState) -> AgentState:
    memory = _short_term_memory
    history = list(state.get("conversation_history", []))
    history.append({"role": "user", "content": state["message"]})
    history.append({"role": "assistant", "content": state.get("response", "")})

    await memory.save_history(state["user_id"], history)
    await _long_term_memory.save_interaction(
        state["user_id"],
        state["message"],
        state.get("response", ""),
        state.get("intent", "other"),
    )

    event_type = "escalated" if state.get("should_escalate") else "response_sent"
    await publish_event_async(
        event_type,
        {
            "user_id": state["user_id"],
            "channel": state.get("channel", ""),
            "message": state["message"],
            "response": state.get("response", ""),
            "intent": state.get("intent", ""),
        },
    )

    return {"conversation_history": history}


def _route_after_escalation_check(state: AgentState) -> str:
    if state.get("should_escalate"):
        return "escalate"
    return "generate_response"


def create_graph():
    builder = StateGraph(AgentState)

    builder.add_node("identify_intent", identify_intent)
    builder.add_node("check_escalation", check_escalation)
    builder.add_node("escalate", escalate)
    builder.add_node("generate_response", generate_response)
    builder.add_node("send_response", send_response)

    builder.add_edge(START, "identify_intent")
    builder.add_edge("identify_intent", "check_escalation")
    builder.add_conditional_edges(
        "check_escalation",
        _route_after_escalation_check,
        {
            "escalate": "escalate",
            "generate_response": "generate_response",
        },
    )
    builder.add_edge("escalate", "send_response")
    builder.add_edge("generate_response", "send_response")
    builder.add_edge("send_response", END)

    return builder.compile()


agent_graph = create_graph()
