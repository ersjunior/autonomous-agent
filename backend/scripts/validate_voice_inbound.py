#!/usr/bin/env python3
"""Validação manual — turno completo inbound de voz (STT → agente → TTS).

Simula a fala do cliente com um WAV em português e mede cada etapa do pipeline
usado pelo record-callback (sem Twilio real).

Uso (stack Docker com GPU, serviços de pé):
  docker exec autonomous-agent-backend python /workspace/backend/scripts/validate_voice_inbound.py
  docker exec autonomous-agent-backend python /workspace/backend/scripts/validate_voice_inbound.py /voices/reference.wav
  docker exec autonomous-agent-backend python /workspace/backend/scripts/validate_voice_inbound.py --from-number +5511948660628
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_ROOT = _BACKEND.parent
for p in (_ROOT, _BACKEND, _ROOT / "worker"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from agents.channels.voice.tts_stt import speech_to_text
from app.core.database import AsyncSessionLocal
from app.services.inbound_attendance import attend_inbound_message
from app.services.settings_sync import bootstrap_settings, ensure_settings_fresh_async
from app.services.voice_audio import gerar_audio_chamada
from worker.tasks.conversation_routing import resolve_inbound_agent
from worker.tasks.lead_tracking import find_lead_by_channel_user

DEFAULT_AUDIO = Path("/voices/reference.wav")
DEFAULT_FROM_NUMBER = "+5511948660628"


def _print_step(label: str, elapsed: float, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"  [{label}] {elapsed:.2f}s{suffix}")


async def run_turn(audio_path: Path, from_number: str) -> int:
    if not audio_path.is_file():
        print(f"[FALHA] Áudio não encontrado: {audio_path}")
        return 1

    print("=== Validação inbound de voz — turno completo (GPU) ===")
    print(f"Áudio: {audio_path} ({audio_path.stat().st_size} bytes)")
    print(f"From (voice): {from_number}")
    print()

    await bootstrap_settings()
    await ensure_settings_fresh_async()

    audio_bytes = audio_path.read_bytes()
    turn_started = time.perf_counter()
    timings: dict[str, float] = {}

    # a) STT
    try:
        t0 = time.perf_counter()
        transcript = (
            await speech_to_text(
                audio_bytes,
                language="pt",
                filename="audio.wav",
                content_type="audio/wav",
            )
        ).strip()
        timings["stt"] = time.perf_counter() - t0
    except Exception as exc:
        print(f"[FALHA] STT (speech_to_text): {exc}")
        return 1

    if not transcript:
        print("[FALHA] STT retornou transcrição vazia")
        return 1

    print(f"Transcrição: {transcript}")
    _print_step("STT", timings["stt"])
    print()

    # b) Lead + agente + c) attend_inbound_message
    async with AsyncSessionLocal() as session:
        try:
            t0 = time.perf_counter()
            lead = await find_lead_by_channel_user(session, "voice", from_number)
            agent = await resolve_inbound_agent(session, lead, "voice", force_receptive=True)
            timings["routing"] = time.perf_counter() - t0
            _print_step(
                "Lead + agente",
                timings["routing"],
                f"lead={lead.id if lead else None} agent={agent.name} ({agent.mode.value})",
            )
        except Exception as exc:
            print(f"[FALHA] Lead/agente (find_lead_by_channel_user / resolve_inbound_agent): {exc}")
            return 1

        try:
            t0 = time.perf_counter()
            response_text = await attend_inbound_message(
                session,
                channel="voice",
                user_id=from_number,
                message=transcript,
                agent=agent,
                lead=lead,
                bind_capacity=False,
            )
            await session.commit()
            timings["agent"] = time.perf_counter() - t0
        except Exception as exc:
            print(f"[FALHA] Agente (attend_inbound_message): {exc}")
            return 1

    response_text = (response_text or "").strip()
    if not response_text:
        print("[FALHA] Agente retornou resposta vazia")
        return 1

    print(f"Resposta do agente: {response_text}")
    _print_step("Agente", timings["agent"])
    print()

    # d) TTS
    try:
        t0 = time.perf_counter()
        mp3_filename = await gerar_audio_chamada(response_text)
        timings["tts"] = time.perf_counter() - t0
    except Exception as exc:
        print(f"[FALHA] TTS (gerar_audio_chamada): {exc}")
        return 1

    print(f"Áudio gerado: {mp3_filename}")
    _print_step("TTS", timings["tts"])
    print()

    timings["total"] = time.perf_counter() - turn_started
    print("=== Resumo de latência ===")
    for key in ("stt", "routing", "agent", "tts", "total"):
        print(f"  {key:8s}: {timings[key]:.2f}s")
    print()
    print("[OK] Turno completo validado.")
    return 0


async def main() -> None:
    parser = argparse.ArgumentParser(description="Valida turno inbound de voz (STT → agente → TTS)")
    parser.add_argument(
        "audio",
        nargs="?",
        default=str(DEFAULT_AUDIO),
        help=f"Caminho do WAV de fala simulada (padrão: {DEFAULT_AUDIO})",
    )
    parser.add_argument(
        "--from-number",
        default=DEFAULT_FROM_NUMBER,
        help=f"Número E.164 do caller de teste (padrão: {DEFAULT_FROM_NUMBER})",
    )
    args = parser.parse_args()

    exit_code = await run_turn(Path(args.audio), args.from_number.strip())
    raise SystemExit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
