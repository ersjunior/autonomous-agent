"""One-off XTTS parameter benchmark (run inside coqui-tts container)."""

from __future__ import annotations

import os
import time

import numpy as np
from TTS.api import TTS

TEXT = (
    "Olá! Estou aqui para ajudar. Como posso ajudá-lo hoje? "
    "Você tem alguma dúvida sobre a ByteCell Academy ou precisa de ajuda "
    "com algo relacionado ao seu curso?"
)
SPEAKER = os.getenv("COQUI_VOICE_SAMPLE", "/voices/reference.wav")

tts = TTS(
    os.getenv("COQUI_MODEL", "tts_models/multilingual/multi-dataset/xtts_v2"),
    gpu=True,
)
xtts = tts.synthesizer.tts_model
gpt, spk = xtts.get_conditioning_latents(audio_path=[SPEAKER])


def measure(params: dict) -> tuple[float, float]:
    t0 = time.perf_counter()
    out = xtts.inference(TEXT, "pt", gpt, spk, **params)
    ms = (time.perf_counter() - t0) * 1000
    wav = np.asarray(out["wav"], dtype=np.float32)
    sr = int(out.get("sample_rate") or 24000)
    return len(wav) / sr, ms


CONFIGS: list[tuple[str, dict]] = [
    ("baseline split=True", {"enable_text_splitting": True}),
    ("split=False", {"enable_text_splitting": False}),
    ("split=False temp=0.55", {"enable_text_splitting": False, "temperature": 0.55}),
    (
        "split=False temp=0.55 rep=10",
        {"enable_text_splitting": False, "temperature": 0.55, "repetition_penalty": 10.0},
    ),
    (
        "split=False temp=0.55 rep=15",
        {"enable_text_splitting": False, "temperature": 0.55, "repetition_penalty": 15.0},
    ),
    ("split=False do_sample=False", {"enable_text_splitting": False, "do_sample": False}),
    ("split=False speed=1.05", {"enable_text_splitting": False, "speed": 1.05}),
]

print(f"chars={len(TEXT)}")
for name, params in CONFIGS:
    try:
        duration, synth_ms = measure(params)
        runon = "YES" if duration > 14.0 else "no"
        print(f"{name:38s} dur={duration:6.2f}s synth_ms={synth_ms:7.0f} runon={runon}")
    except Exception as exc:
        print(f"{name:38s} ERROR {exc}")
