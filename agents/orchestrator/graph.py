"""LangGraph orchestrator for customer service conversations."""

import logging

from langgraph.graph import END, START, StateGraph

from agents.events import publish_event_async
from agents.memory.long_term import LongTermMemory
from agents.memory.short_term import ShortTermMemory
from agents.orchestrator.router import route_after_escalation_check
from agents.orchestrator.state import AgentState
from agents.workers.intent_agent import identify_intent as run_identify_intent
from agents.workers.response_agent import generate_response as run_generate_response

logger = logging.getLogger(__name__)

ESCALATION_CONFIDENCE_THRESHOLD = 0.5
EMPTY_RESPONSE_FALLBACK = (
    "Desculpe, não consegui processar sua mensagem agora. Pode reformular?"
)

_short_term_memory = ShortTermMemory()
_long_term_memory = LongTermMemory()


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
    # RAG no nó do grafo: tem user_id + message; falha não bloqueia a resposta.
    rag_memories = await _long_term_memory.retrieve_similar_memories(
        state["user_id"],
        state["message"],
    )
    text = await run_generate_response(
        state["message"],
        state.get("intent", "other"),
        state.get("entities", {}),
        state.get("conversation_history", []),
        state.get("channel", ""),
        rag_memories=rag_memories,
        agent_personality=state.get("agent_personality"),
    )
    return {"response": text, "rag_memories": rag_memories}


async def send_response(state: AgentState) -> AgentState:
    memory = _short_term_memory
    response = (state.get("response") or "").strip()
    if not response:
        logger.warning(
            "Empty LLM response for user_id=%s channel=%s",
            state["user_id"],
            state.get("channel", ""),
        )
        response = EMPTY_RESPONSE_FALLBACK

    history = list(state.get("conversation_history", []))
    history.append({"role": "user", "content": state["message"]})
    history.append({"role": "assistant", "content": response})

    await memory.save_history(state["user_id"], history)
    await _long_term_memory.save_interaction(
        state["user_id"],
        state["message"],
        response,
        state.get("intent", "other"),
    )

    event_type = "escalated" if state.get("should_escalate") else "response_sent"
    await publish_event_async(
        event_type,
        {
            "user_id": state["user_id"],
            "channel": state.get("channel", ""),
            "message": state["message"],
            "response": response,
            "intent": state.get("intent", ""),
        },
    )

    return {"conversation_history": history, "response": response}


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
        route_after_escalation_check,
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
