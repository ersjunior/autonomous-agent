"""Phrase-by-phrase XTTS benchmark."""

from __future__ import annotations

import os
import re
import time

import numpy as np
from TTS.api import TTS

TEXT = (
    "Olá! Estou aqui para ajudar. Como posso ajudá-lo hoje? "
    "Você tem alguma dúvida sobre a ByteCell Academy ou precisa de ajuda "
    "com algo relacionado ao seu curso?"
)
SPEAKER = os.getenv("COQUI_VOICE_SAMPLE", "/voices/reference.wav")
PARAMS = {"enable_text_splitting": False, "temperature": 0.65, "repetition_penalty": 10.0}

tts = TTS(
    os.getenv("COQUI_MODEL", "tts_models/multilingual/multi-dataset/xtts_v2"),
    gpu=True,
)
xtts = tts.synthesizer.tts_model
gpt, spk = xtts.get_conditioning_latents(audio_path=[SPEAKER])


def split_phrases(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def synth_one(text: str) -> tuple[np.ndarray, int]:
    out = xtts.inference(text, "pt", gpt, spk, **PARAMS)
    wav = np.asarray(out["wav"], dtype=np.float32)
    sr = int(out.get("sample_rate") or 24000)
    return wav, sr


phrases = split_phrases(TEXT)
print(f"chars={len(TEXT)} phrases={len(phrases)}")
for i, p in enumerate(phrases, 1):
    print(f"  {i}: {len(p)} chars | {p[:60]}{'...' if len(p)>60 else ''}")

t0 = time.perf_counter()
chunks: list[np.ndarray] = []
sr = 24000
gap = np.zeros(int(sr * 0.15), dtype=np.float32)
for i, phrase in enumerate(phrases):
    wav, sr = synth_one(phrase)
    chunks.append(wav)
    if i < len(phrases) - 1:
        chunks.append(gap)
combined = np.concatenate(chunks)
ms = (time.perf_counter() - t0) * 1000
print(f"phrase-by-phrase total_dur={len(combined)/sr:.2f}s synth_ms={ms:.0f}")

t0 = time.perf_counter()
out = xtts.inference(TEXT, "pt", gpt, spk, **PARAMS)
ms = (time.perf_counter() - t0) * 1000
wav = np.asarray(out["wav"], dtype=np.float32)
print(f"single-pass split=False total_dur={len(wav)/sr:.2f}s synth_ms={ms:.0f}")
