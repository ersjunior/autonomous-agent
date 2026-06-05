"""
Capacidade global ponderada (R-A) — ativo + receptivo compartilham o mesmo teto.

Chaves Redis:
  global_capacity_usage              — soma dos pesos em uso (INT)
  global_capacity_holders              — SET de tokens ativos
  global_capacity_holder:{token}     — peso (INT) com TTL (rede de segurança)
  contact_capacity:{channel}:{user}  — global_token:weight:agent_id:slot_token
  lead_capacity_user:{lead_id}:{ch}  — user_id (liberação ao status terminal)

Aquisição atômica via Lua (padrão Camada D). Subteto local continua em activation_slots.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

import redis

from app.core.activation_defaults import channel_weight, normalize_channel_type
from app.core.config import settings
from app.services.capacity_estimate import resolve_max_weighted_capacity
from app.services.activation_slots import (
    bind_lead_slot,
    release_slot,
    slot_ttl_seconds,
    try_acquire_slot,
)

logger = logging.getLogger(__name__)

_redis_client: redis.Redis | None = None

USAGE_KEY = "global_capacity_usage"
HOLDERS_SET_KEY = "global_capacity_holders"

_LUA_TRY_ACQUIRE_GLOBAL = """
local usage_key = KEYS[1]
local holders_set = KEYS[2]
local holder_key = KEYS[3]
local max_cap = tonumber(ARGV[1])
local weight = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
local token = ARGV[4]

local current = tonumber(redis.call('GET', usage_key) or '0')
if current + weight > max_cap then
  return 0
end
redis.call('INCRBY', usage_key, weight)
redis.call('SADD', holders_set, token)
redis.call('SET', holder_key, weight, 'EX', ttl)
return 1
"""

_LUA_RELEASE_GLOBAL = """
local usage_key = KEYS[1]
local holders_set = KEYS[2]
local holder_key = KEYS[3]
local token = ARGV[1]

if redis.call('EXISTS', holder_key) == 0 then
  return 0
end
local weight = tonumber(redis.call('GET', holder_key))
redis.call('DEL', holder_key)
redis.call('SREM', holders_set, token)
local new_usage = tonumber(redis.call('DECRBY', usage_key, weight))
if new_usage < 0 then
  redis.call('SET', usage_key, '0')
end
return 1
"""


@dataclass(frozen=True)
class ReceptiveCapacityHandle:
    global_token: str
    weight: int
    slot_token: str
    agent_id: str


@dataclass(frozen=True)
class OutboundCapacityHandle:
    global_token: str
    weight: int
    slot_token: str
    agent_id: str


def _outbound_capacity_key(lead_id: str, channel: str) -> str:
    ch = normalize_channel_type(channel)
    return f"outbound_capacity:{lead_id}:{ch}"


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def _holder_key(token: str) -> str:
    return f"global_capacity_holder:{token}"


def _contact_capacity_key(channel: str, user_id: str) -> str:
    ch = normalize_channel_type(channel)
    return f"contact_capacity:{ch}:{user_id}"


def _lead_capacity_user_key(lead_id: str, channel: str) -> str:
    ch = normalize_channel_type(channel)
    return f"lead_capacity_user:{lead_id}:{ch}"


def _reconcile_expired_global_holders() -> int:
    """Recalcula usage a partir dos holders vivos (TTL expirado → remove do SET)."""
    client = _get_redis()
    tokens = list(client.smembers(HOLDERS_SET_KEY))
    total = 0
    removed = 0
    for token in tokens:
        holder = _holder_key(token)
        weight_raw = client.get(holder)
        if weight_raw is None:
            client.srem(HOLDERS_SET_KEY, token)
            removed += 1
        else:
            total += int(weight_raw)
    client.set(USAGE_KEY, str(total))
    return removed


def current_global_usage() -> int:
    _reconcile_expired_global_holders()
    return max(0, int(_get_redis().get(USAGE_KEY) or 0))


def try_acquire_global(
    weight: int,
    ttl_seconds: int | None = None,
    *,
    max_capacity: int | None = None,
) -> str | None:
    """Ocupa peso no teto global. Retorna token ou None."""
    if weight < 1:
        return None
    _reconcile_expired_global_holders()
    ttl = ttl_seconds if ttl_seconds is not None else settings.chat_slot_ttl_seconds
    cap = max_capacity if max_capacity is not None else resolve_max_weighted_capacity()
    token = uuid.uuid4().hex
    ok = _get_redis().eval(
        _LUA_TRY_ACQUIRE_GLOBAL,
        3,
        USAGE_KEY,
        HOLDERS_SET_KEY,
        _holder_key(token),
        cap,
        weight,
        ttl,
        token,
    )
    if int(ok) != 1:
        return None
    return token


def release_global(token: str | None, weight: int | None = None) -> bool:
    """Libera peso global (idempotente). Se weight omitido, lê do holder."""
    if not token:
        return False
    client = _get_redis()
    holder = _holder_key(token)
    if weight is None:
        raw = client.get(holder)
        if raw is None:
            client.srem(HOLDERS_SET_KEY, token)
            return False
        weight = int(raw)
    released = client.eval(
        _LUA_RELEASE_GLOBAL,
        3,
        USAGE_KEY,
        HOLDERS_SET_KEY,
        holder,
        token,
    )
    return int(released) == 1


def _local_slot_limit(params: dict[str, Any], channel: str) -> int:
    family = normalize_channel_type(channel)
    if family in ("voice", "video"):
        return int(params.get("chamadas_simultaneas", 1))
    return int(params.get("chats_simultaneos", 5))


def try_acquire_receptive_capacity(
    agent_id: str,
    channel: str,
    params: dict[str, Any],
) -> ReceptiveCapacityHandle | None:
    """
    Adquire capacidade global (peso) + slot local (agent, channel).
    Se slot falhar, reverte o global.
    """
    ch = normalize_channel_type(channel)
    weight = channel_weight(ch)
    global_token = try_acquire_global(weight, ttl_seconds=slot_ttl_seconds(ch))
    if global_token is None:
        return None
    limit = _local_slot_limit(params, ch)
    slot_token = try_acquire_slot(str(agent_id), ch, limit, ttl_seconds=slot_ttl_seconds(ch))
    if slot_token is None:
        release_global(global_token, weight)
        return None
    return ReceptiveCapacityHandle(
        global_token=global_token,
        weight=weight,
        slot_token=slot_token,
        agent_id=str(agent_id),
    )


def bind_contact_capacity(
    channel: str,
    user_id: str,
    handle: ReceptiveCapacityHandle,
    *,
    lead_id: str | None = None,
    ttl_seconds: int | None = None,
) -> None:
    """Mapeia contato → tokens para liberação ao encerrar conversa."""
    ch = normalize_channel_type(channel)
    ttl = ttl_seconds if ttl_seconds is not None else slot_ttl_seconds(ch)
    payload = json.dumps(
        {
            "global_token": handle.global_token,
            "weight": handle.weight,
            "agent_id": handle.agent_id,
            "slot_token": handle.slot_token,
        }
    )
    client = _get_redis()
    client.set(_contact_capacity_key(ch, user_id), payload, ex=ttl)
    if lead_id:
        client.set(_lead_capacity_user_key(lead_id, ch), user_id, ex=ttl)
        bind_lead_slot(lead_id, ch, handle.agent_id, handle.slot_token, ttl_seconds=ttl)


def release_receptive_handle(handle: ReceptiveCapacityHandle, channel: str) -> bool:
    """Libera slot local + peso global adquiridos mas não vinculados ao contato."""
    ch = normalize_channel_type(channel)
    released_slot = release_slot(handle.agent_id, ch, handle.slot_token)
    released_global = release_global(handle.global_token, handle.weight)
    return released_slot or released_global


def release_contact_capacity(channel: str, user_id: str) -> bool:
    """Libera slot local + peso global para um contato."""
    ch = normalize_channel_type(channel)
    client = _get_redis()
    raw = client.get(_contact_capacity_key(ch, user_id))
    if not raw:
        return False
    client.delete(_contact_capacity_key(ch, user_id))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False
    global_token = data.get("global_token")
    weight = int(data.get("weight", 0))
    agent_id = data.get("agent_id")
    slot_token = data.get("slot_token")
    released_slot = release_slot(agent_id, ch, slot_token)
    released_global = release_global(global_token, weight)
    if released_slot or released_global:
        logger.debug(
            "Released receptive capacity channel=%s user=%s agent=%s",
            ch,
            user_id,
            agent_id,
        )
    return released_slot or released_global


def release_receptive_capacity_for_lead(lead_id: str, channel: str) -> bool:
    """Libera capacidade ao status terminal (via mapeamento lead → user_id)."""
    ch = normalize_channel_type(channel)
    client = _get_redis()
    user_id = client.get(_lead_capacity_user_key(str(lead_id), ch))
    if not user_id:
        return False
    client.delete(_lead_capacity_user_key(str(lead_id), ch))
    return release_contact_capacity(ch, user_id)


def remaining_global_capacity() -> int:
    return max(0, resolve_max_weighted_capacity() - current_global_usage())


def can_acquire_global(weight: int) -> bool:
    return current_global_usage() + weight <= resolve_max_weighted_capacity()


def try_acquire_outbound_capacity(
    agent_id: str,
    channel: str,
    params: dict[str, Any],
) -> OutboundCapacityHandle | None:
    """
    Outbound ativo (Camada D): peso global + slot local.

    Se o global estiver cheio, retorna None (scheduler re-enfileira na priority queue).
    """
    ch = normalize_channel_type(channel)
    weight = channel_weight(ch)
    global_token = try_acquire_global(weight, ttl_seconds=slot_ttl_seconds(ch))
    if global_token is None:
        return None
    limit = _local_slot_limit(params, ch)
    slot_token = try_acquire_slot(str(agent_id), ch, limit, ttl_seconds=slot_ttl_seconds(ch))
    if slot_token is None:
        release_global(global_token, weight)
        return None
    return OutboundCapacityHandle(
        global_token=global_token,
        weight=weight,
        slot_token=slot_token,
        agent_id=str(agent_id),
    )


def bind_outbound_capacity(
    lead_id: str,
    channel: str,
    handle: OutboundCapacityHandle,
    *,
    ttl_seconds: int | None = None,
) -> None:
    """Mapeia lead outbound → tokens (liberação ao status terminal / falha de entrega)."""
    ch = normalize_channel_type(channel)
    ttl = ttl_seconds if ttl_seconds is not None else slot_ttl_seconds(ch)
    payload = json.dumps(
        {
            "global_token": handle.global_token,
            "weight": handle.weight,
            "agent_id": handle.agent_id,
            "slot_token": handle.slot_token,
        }
    )
    _get_redis().set(_outbound_capacity_key(str(lead_id), ch), payload, ex=ttl)
    bind_lead_slot(str(lead_id), ch, handle.agent_id, handle.slot_token, ttl_seconds=ttl)


def release_outbound_capacity_for_lead(lead_id: str, channel: str) -> bool:
    """Libera slot + peso global do outbound para o lead."""
    ch = normalize_channel_type(channel)
    client = _get_redis()
    raw = client.get(_outbound_capacity_key(str(lead_id), ch))
    if not raw:
        return False
    client.delete(_outbound_capacity_key(str(lead_id), ch))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False
    global_token = data.get("global_token")
    weight = int(data.get("weight", 0))
    agent_id = data.get("agent_id")
    slot_token = data.get("slot_token")
    from app.services.activation_slots import release_slot_for_lead

    released_slot = release_slot(agent_id, ch, slot_token)
    released_global = release_global(global_token, weight)
    released_slot |= release_slot_for_lead(str(lead_id), ch)
    return released_slot or released_global


def release_outbound_handle(handle: OutboundCapacityHandle, lead_id: str, channel: str) -> bool:
    """Libera após dispatch sem bind de lead (falha antes de bind)."""
    ch = normalize_channel_type(channel)
    released_slot = release_slot(handle.agent_id, ch, handle.slot_token)
    released_global = release_global(handle.global_token, handle.weight)
    return released_slot or released_global


def _sum_bound_capacity_weight(key_pattern: str) -> int:
    total = 0
    for key in _get_redis().scan_iter(key_pattern):
        raw = _get_redis().get(key)
        if not raw:
            continue
        try:
            data = json.loads(raw)
            total += int(data.get("weight", 0))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return total


def current_receptive_bound_weight() -> int:
    return _sum_bound_capacity_weight("contact_capacity:*")


def current_outbound_bound_weight() -> int:
    return _sum_bound_capacity_weight("outbound_capacity:*")
