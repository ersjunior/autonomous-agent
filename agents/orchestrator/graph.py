"""LangGraph orchestrator for customer service conversations."""

import logging

from langgraph.graph import END, START, StateGraph

from agents.events import publish_event_async
from agents.memory.long_term import LongTermMemory
from agents.memory.short_term import ShortTermMemory
from agents.orchestrator.router import route_after_escalation_check
from agents.orchestrator.state import AgentState
from agents.tools.knowledge_base import retrieve_kb_chunks
from agents.escalation import resolve_should_escalate
from agents.workers.intent_agent import identify_intent as run_identify_intent
from agents.workers.response_agent import generate_response as run_generate_response

logger = logging.getLogger(__name__)

EMPTY_RESPONSE_FALLBACK = (
    "Desculpe, não consegui processar sua mensagem agora. Pode reformular?"
)

_short_term_memory = ShortTermMemory()
_long_term_memory = LongTermMemory()


async def reset_worker_async_clients() -> None:
    """
    Recria clientes async globais após ``asyncio.run`` em tasks Celery (prefork).

    O Redis de ``ShortTermMemory`` fica ligado ao event loop da execução anterior;
    sem reset, a task seguinte no mesmo worker pode falhar com loop fechado.
    """
    global _short_term_memory
    try:
        await _short_term_memory._redis.aclose()
    except Exception:
        pass
    _short_term_memory = ShortTermMemory()


async def close_long_term_pgvector_pool() -> None:
    """Fecha o pool asyncpg de memória de longo prazo (worker Celery cleanup)."""
    await _long_term_memory._pool_holder.close()


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
            "complaint_severity": result.complaint_severity,
        },
    )
    return {
        "intent": result.intent,
        "confidence": result.confidence,
        "entities": result.entities,
        "complaint_severity": result.complaint_severity,
        "conversation_history": history,
    }


async def check_escalation(state: AgentState) -> AgentState:
    should_escalate = resolve_should_escalate(
        state.get("intent", ""),
        state.get("confidence", 1.0),
        state.get("complaint_severity", "low"),
    )
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
    # Dois RAGs complementares: memória do contato + base documental do dono/institucional.
    rag_memories = await _long_term_memory.retrieve_similar_memories(
        state["user_id"],
        state["message"],
    )
    kb_chunks = await retrieve_kb_chunks(
        state.get("owner_user_id"),
        state["message"],
    )
    text = await run_generate_response(
        state["message"],
        state.get("intent", "other"),
        state.get("entities", {}),
        state.get("conversation_history", []),
        state.get("channel", ""),
        rag_memories=rag_memories,
        kb_chunks=kb_chunks,
        agent_personality=state.get("agent_personality"),
        agent_mode=state.get("agent_mode"),
    )
    return {"response": text, "rag_memories": rag_memories, "kb_chunks": kb_chunks}


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
