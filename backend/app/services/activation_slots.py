"""
Camada D — slots de concorrência atômicos no Redis + fila de prioridade (ZSET).

Atomicidade: scripts Lua (EVAL) para acquire/release/pop sem corrida entre workers.
Contagem: SET de tokens ativos + chave holder com TTL; reconcile remove tokens cujo
holder expirou (rede de segurança contra slot fantasma sem callback Twilio).

Chaves:
  slots_set:{agent_id}:{channel}              — SET de tokens ocupados
  slot_holder:{agent_id}:{channel}:{token}    — marcador com TTL
  priority_queue:{agent_id}:{channel}         — ZSET (member=campaign_id:lead_id[:followup], score=ts)
  lead_slot:{lead_id}:{channel}               — agent_id:token (liberação ao encerrar conversa)
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import NamedTuple

import redis

from app.core.activation_defaults import channel_family, normalize_channel_type
from app.core.config import settings

logger = logging.getLogger(__name__)

_redis_client: redis.Redis | None = None

# --- Lua: acquire (SCARD < limit → SADD + SET holder EX) ---
_LUA_TRY_ACQUIRE = """
local set_key = KEYS[1]
local holder_key = KEYS[2]
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local token = ARGV[3]

local active = redis.call('SCARD', set_key)
if active >= limit then
  return 0
end
redis.call('SADD', set_key, token)
redis.call('SET', holder_key, '1', 'EX', ttl)
return 1
"""

# --- Lua: release idempotente (holder existe → DEL + SREM) ---
_LUA_RELEASE = """
local set_key = KEYS[1]
local holder_key = KEYS[2]
local token = ARGV[1]

if redis.call('EXISTS', holder_key) == 0 then
  return 0
end
redis.call('DEL', holder_key)
redis.call('SREM', set_key, token)
return 1
"""

# --- Lua: pop até max_n membros do ZSET (menor score primeiro) ---
_LUA_POP_PRIORITY = """
local key = KEYS[1]
local max_n = tonumber(ARGV[1])
local n = tonumber(redis.call('ZCARD', key))
if n == 0 then
  return {}
end
if max_n < n then
  n = max_n
end
local members = redis.call('ZRANGE', key, 0, n - 1)
for i, m in ipairs(members) do
  redis.call('ZREM', key, m)
end
return members
"""


class PriorityMember(NamedTuple):
    campaign_id: str
    lead_id: str
    is_followup: bool


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def _slots_set_key(agent_id: str, channel_type: str) -> str:
    ch = normalize_channel_type(channel_type)
    return f"slots_set:{agent_id}:{ch}"


def _holder_key(agent_id: str, channel_type: str, token: str) -> str:
    ch = normalize_channel_type(channel_type)
    return f"slot_holder:{agent_id}:{ch}:{token}"


def _priority_key(agent_id: str, channel_type: str) -> str:
    ch = normalize_channel_type(channel_type)
    return f"priority_queue:{agent_id}:{ch}"


def _lead_slot_key(lead_id: str, channel_type: str) -> str:
    ch = normalize_channel_type(channel_type)
    return f"lead_slot:{lead_id}:{ch}"


def priority_member(campaign_id: str, lead_id: str, *, followup: bool = False) -> str:
    base = f"{campaign_id}:{lead_id}"
    return f"{base}:followup" if followup else base


def parse_priority_member(member: str) -> PriorityMember | None:
    parts = member.split(":")
    if len(parts) < 2:
        return None
    if parts[-1] == "followup":
        return PriorityMember(
            campaign_id=parts[0],
            lead_id=parts[1],
            is_followup=True,
        )
    if len(parts) == 2:
        return PriorityMember(campaign_id=parts[0], lead_id=parts[1], is_followup=False)
    return None


def _reconcile_expired_holders(agent_id: str, channel_type: str) -> int:
    """Remove tokens do SET cujo holder TTL expirou (contador efetivo)."""
    client = _get_redis()
    set_key = _slots_set_key(agent_id, channel_type)
    tokens = client.smembers(set_key)
    removed = 0
    for token in tokens:
        if not client.exists(_holder_key(agent_id, channel_type, token)):
            client.srem(set_key, token)
            removed += 1
    return removed


def count_active_slots(agent_id: str, channel_type: str) -> int:
    _reconcile_expired_holders(agent_id, channel_type)
    return int(_get_redis().scard(_slots_set_key(agent_id, channel_type)))


def slot_ttl_seconds(channel_type: str) -> int:
    family = channel_family(channel_type)
    if family == "voice":
        return settings.call_slot_ttl_seconds
    return settings.chat_slot_ttl_seconds


def try_acquire_slot(
    agent_id: str,
    channel_type: str,
    limit: int,
    ttl_seconds: int | None = None,
) -> str | None:
    """
    Ocupa um slot de forma atômica (Lua). Retorna token ou None se cheio.
    """
    if limit < 1:
        return None
    _reconcile_expired_holders(agent_id, channel_type)
    ttl = ttl_seconds if ttl_seconds is not None else slot_ttl_seconds(channel_type)
    token = uuid.uuid4().hex
    client = _get_redis()
    ok = client.eval(
        _LUA_TRY_ACQUIRE,
        2,
        _slots_set_key(agent_id, channel_type),
        _holder_key(agent_id, channel_type, token),
        limit,
        ttl,
        token,
    )
    if int(ok) != 1:
        return None
    return token


def release_slot(agent_id: str, channel_type: str, token: str | None) -> bool:
    """Libera slot (idempotente). Retorna True se liberou."""
    if not token:
        return False
    client = _get_redis()
    released = client.eval(
        _LUA_RELEASE,
        2,
        _slots_set_key(agent_id, channel_type),
        _holder_key(agent_id, channel_type, token),
        token,
    )
    return int(released) == 1


def bind_lead_slot(
    lead_id: str,
    channel_type: str,
    agent_id: str,
    token: str,
    *,
    ttl_seconds: int | None = None,
) -> None:
    """Mapeia lead+canal → agent:token para liberação ao encerrar conversa (messaging)."""
    ttl = ttl_seconds if ttl_seconds is not None else slot_ttl_seconds(channel_type)
    _get_redis().set(
        _lead_slot_key(lead_id, channel_type),
        f"{agent_id}:{token}",
        ex=ttl,
    )


def release_slot_for_lead(lead_id: str, channel_type: str) -> bool:
    """Libera slot de conversa messaging quando lead encerra (status terminal, etc.)."""
    client = _get_redis()
    raw = client.get(_lead_slot_key(lead_id, channel_type))
    if not raw:
        return False
    client.delete(_lead_slot_key(lead_id, channel_type))
    if ":" not in raw:
        return False
    agent_id, token = raw.split(":", 1)
    released = release_slot(agent_id, channel_type, token)
    if released:
        logger.debug(
            "Released messaging slot lead=%s channel=%s agent=%s",
            lead_id,
            channel_type,
            agent_id,
        )
    return released


def enqueue_priority(
    agent_id: str,
    channel_type: str,
    campaign_id: str,
    lead_id: str,
    score: float | None = None,
    *,
    followup: bool = False,
) -> None:
    """Adiciona lead pulado à fila (score = elegibilidade). NX preserva score mais antigo."""
    member = priority_member(campaign_id, lead_id, followup=followup)
    sc = score if score is not None else time.time()
    _get_redis().zadd(
        _priority_key(agent_id, channel_type),
        {member: sc},
        nx=True,
    )


def remove_from_priority(
    agent_id: str,
    channel_type: str,
    campaign_id: str,
    lead_id: str,
    *,
    followup: bool = False,
) -> None:
    _get_redis().zrem(
        _priority_key(agent_id, channel_type),
        priority_member(campaign_id, lead_id, followup=followup),
    )


def pop_priority_leads(
    agent_id: str,
    channel_type: str,
    max_n: int,
) -> list[PriorityMember]:
    if max_n < 1:
        return []
    client = _get_redis()
    raw = client.eval(
        _LUA_POP_PRIORITY,
        1,
        _priority_key(agent_id, channel_type),
        max_n,
    )
    if not raw:
        return []
    out: list[PriorityMember] = []
    for member in raw:
        parsed = parse_priority_member(member)
        if parsed:
            out.append(parsed)
    return out


def priority_queue_size(agent_id: str, channel_type: str) -> int:
    return int(_get_redis().zcard(_priority_key(agent_id, channel_type)))


def _inflight_key(campaign_id: str, lead_id: str, channel_type: str) -> str:
    ch = normalize_channel_type(channel_type)
    return f"dispatch_inflight:{campaign_id}:{ch}:{lead_id}"


def mark_dispatch_inflight(
    campaign_id: str,
    lead_id: str,
    channel_type: str,
    *,
    ttl_seconds: int = 600,
) -> bool:
    """Marca disparo enfileirado (evita duplicar scheduler/priority_queue)."""
    return bool(
        _get_redis().set(
            _inflight_key(campaign_id, lead_id, channel_type),
            "1",
            nx=True,
            ex=ttl_seconds,
        )
    )


def is_dispatch_inflight(campaign_id: str, lead_id: str, channel_type: str) -> bool:
    return bool(_get_redis().exists(_inflight_key(campaign_id, lead_id, channel_type)))


def clear_dispatch_inflight(campaign_id: str, lead_id: str, channel_type: str) -> None:
    _get_redis().delete(_inflight_key(campaign_id, lead_id, channel_type))
