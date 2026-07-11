"""LangGraph orchestrator for customer service conversations."""

import asyncio
import logging
import time

from langgraph.graph import END, START, StateGraph

from agents.events import publish_event_async
from agents.memory.long_term import LongTermMemory
from agents.memory.short_term import ShortTermMemory, conversation_memory_key
from agents.orchestrator.booking_handler import process_booking_turn
from agents.orchestrator.farewell_handler import (
    apply_hangup_decision,
    detect_user_farewell_signal,
)
from agents.orchestrator.router import route_after_escalation_check
from agents.orchestrator.state import AgentState
from agents.services.embedding_service import embed_text
from agents.tools.knowledge_base import _retriever as _kb_retriever
from agents.escalation import resolve_should_escalate
from agents.workers.intent_agent import identify_intent as run_identify_intent
from agents.workers.response_agent import generate_response as run_generate_response
from agents.workers.voice_intent_heuristic import identify_intent_voice_heuristic
from app.core.config import settings

logger = logging.getLogger(__name__)


def _agent_event_fields(state: AgentState) -> dict:
    """Optional agent metadata for monitoring events (backward-compatible)."""
    fields: dict = {}
    agent_id = state.get("agent_id")
    agent_name = state.get("agent_name")
    if agent_id:
        fields["agent_id"] = agent_id
    if agent_name:
        fields["agent_name"] = agent_name
    return fields


EMPTY_RESPONSE_FALLBACK = (
    "Desculpe, não consegui processar sua mensagem agora. Pode reformular?"
)

_short_term_memory = ShortTermMemory()
_long_term_memory = LongTermMemory()


def _dialog_memory_key(state: AgentState) -> str:
    """Short-term dialog Redis key — voice calls use CallSid; other channels use user_id."""
    return conversation_memory_key(
        state["channel"],
        state["user_id"],
        twilio_call_sid=state.get("twilio_call_sid"),
    )


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
    memory_key = _dialog_memory_key(state)
    history = await memory.get_history(memory_key, channel=state.get("channel"))
    channel = (state.get("channel") or "").lower()
    t0 = time.perf_counter()

    if channel == "voice":
        result = identify_intent_voice_heuristic(state["message"])
        intent_ms = (time.perf_counter() - t0) * 1000
        logger.debug(
            "Voice intent heuristic intent=%s confidence=%s intent_ms=%.0f",
            result.intent,
            result.confidence,
            intent_ms,
        )
    else:
        result = await run_identify_intent(
            state["message"],
            history,
        )
        intent_ms = (time.perf_counter() - t0) * 1000

    await publish_event_async(
        "intent_detected",
        {
            "user_id": state["user_id"],
            "channel": state.get("channel", ""),
            "message": state["message"],
            "intent": result.intent,
            "confidence": result.confidence,
            "complaint_severity": result.complaint_severity,
            **_agent_event_fields(state),
        },
    )
    return {
        "intent": result.intent,
        "confidence": result.confidence,
        "entities": result.entities,
        "complaint_severity": result.complaint_severity,
        "conversation_history": history,
        "intent_ms": intent_ms,
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


async def _fetch_rag_context(state: AgentState) -> tuple[list[dict], list[dict], float]:
    """
    Um embedding + buscas memória/KB em paralelo.

    Voice: só base de conhecimento (KB); histórico de conversas passadas do lead é omitido
    (cada ligação usa apenas chat:{call_sid} + KB). Demais canais: memória + KB.
    KB: resolved_kb_top_k() global; voice usa voice_kb_similarity_threshold.
    """
    message = (state.get("message") or "").strip()
    if not message:
        return [], [], 0.0

    channel = (state.get("channel") or "").lower()
    is_voice = channel == "voice"
    memory_limit = settings.voice_rag_top_k if is_voice else None
    memory_threshold = settings.voice_rag_similarity_threshold if is_voice else None
    kb_top_k = None  # resolved_kb_top_k() dentro do retriever
    kb_threshold = settings.voice_kb_similarity_threshold if is_voice else None

    t0 = time.perf_counter()
    try:
        query_embedding = await embed_text(message)
        if is_voice:
            kb_chunks = await _kb_retriever.retrieve_kb_chunks(
                state.get("owner_user_id"),
                message,
                top_k=kb_top_k,
                threshold=kb_threshold,
                query_embedding=query_embedding,
            )
            rag_memories: list[dict] = []
        else:
            rag_memories, kb_chunks = await asyncio.gather(
                _long_term_memory.retrieve_similar_memories(
                    state["user_id"],
                    message,
                    limit=memory_limit,
                    threshold=memory_threshold,
                    query_embedding=query_embedding,
                ),
                _kb_retriever.retrieve_kb_chunks(
                    state.get("owner_user_id"),
                    message,
                    top_k=kb_top_k,
                    threshold=kb_threshold,
                    query_embedding=query_embedding,
                ),
            )
    except Exception:
        logger.warning(
            "Parallel RAG failed user_id=%s; falling back to sequential",
            state.get("user_id"),
            exc_info=True,
        )
        if is_voice:
            rag_memories = []
            kb_chunks = await _kb_retriever.retrieve_kb_chunks(
                state.get("owner_user_id"),
                message,
                top_k=kb_top_k,
                threshold=kb_threshold,
            )
        else:
            rag_memories = await _long_term_memory.retrieve_similar_memories(
                state["user_id"],
                message,
                limit=memory_limit,
                threshold=memory_threshold,
            )
            kb_chunks = await _kb_retriever.retrieve_kb_chunks(
                state.get("owner_user_id"),
                message,
                top_k=kb_top_k,
                threshold=kb_threshold,
            )
    rag_ms = (time.perf_counter() - t0) * 1000
    return rag_memories, kb_chunks, rag_ms


async def handle_booking(state: AgentState) -> AgentState:
    """Avança fluxo de agendamento e prepara contexto para o LLM de resposta."""
    result = await process_booking_turn(state)
    return result


async def handle_farewell(state: AgentState) -> AgentState:
    """Detecta sinal de encerramento no transcript do usuário (pré-LLM)."""
    return detect_user_farewell_signal(state)


async def finalize_hangup(state: AgentState) -> AgentState:
    """Dupla confirmação pós-LLM: usuário despediu + agente não pergunta + despedida clara."""
    return apply_hangup_decision(state)


async def generate_response(state: AgentState) -> AgentState:
    channel = (state.get("channel") or "").lower()
    prebuilt = (state.get("response") or "").strip()
    voice_prebuilt = channel == "voice" and prebuilt and state.get("booking_phase") is not None
    if voice_prebuilt:
        from agents.workers.response_agent import sanitize_voice_response_for_telephony

        return {
            "response": sanitize_voice_response_for_telephony(prebuilt),
            "rag_memories": [],
            "kb_chunks": [],
            "rag_ms": 0.0,
            "response_ms": 0.0,
        }

    rag_memories, kb_chunks, rag_ms = await _fetch_rag_context(state)
    t0 = time.perf_counter()
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
        agent_config=state.get("agent_config"),
        booking_context=state.get("booking_context"),
    )
    response_ms = (time.perf_counter() - t0) * 1000
    if rag_ms > 0:
        logger.debug(
            "RAG+LLM timings channel=%s rag_ms=%.0f response_ms=%.0f top_k=%s",
            state.get("channel", ""),
            rag_ms,
            response_ms,
            settings.voice_rag_top_k
            if (state.get("channel") or "").lower() == "voice"
            else settings.rag_top_k,
        )
    return {
        "response": text,
        "rag_memories": rag_memories,
        "kb_chunks": kb_chunks,
        "rag_ms": rag_ms,
        "response_ms": response_ms,
    }


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

    memory_key = _dialog_memory_key(state)
    await memory.save_history(memory_key, history, channel=state.get("channel"))
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
            **_agent_event_fields(state),
        },
    )

    return {"conversation_history": history, "response": response}


def create_graph():
    builder = StateGraph(AgentState)

    builder.add_node("identify_intent", identify_intent)
    builder.add_node("check_escalation", check_escalation)
    builder.add_node("escalate", escalate)
    builder.add_node("handle_booking", handle_booking)
    builder.add_node("handle_farewell", handle_farewell)
    builder.add_node("finalize_hangup", finalize_hangup)
    builder.add_node("generate_response", generate_response)
    builder.add_node("send_response", send_response)

    builder.add_edge(START, "identify_intent")
    builder.add_edge("identify_intent", "check_escalation")
    builder.add_conditional_edges(
        "check_escalation",
        route_after_escalation_check,
        {
            "escalate": "escalate",
            "handle_booking": "handle_booking",
        },
    )
    builder.add_edge("escalate", "send_response")
    builder.add_edge("handle_booking", "handle_farewell")
    builder.add_edge("handle_farewell", "generate_response")
    builder.add_edge("generate_response", "finalize_hangup")
    builder.add_edge("finalize_hangup", "send_response")
    builder.add_edge("send_response", END)

    return builder.compile()


agent_graph = create_graph()
