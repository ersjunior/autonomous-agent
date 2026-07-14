#!/usr/bin/env python3
"""Benchmark XTTS speed values (run inside coqui-tts container)."""

from __future__ import annotations

import io
import json
import os
import sys
import time
import wave
from pathlib import Path

# Sample ~100 chars (typical capped voice response)
SAMPLE_TEXT = (
    "A ByteCell Academy oferece cursos de Excel, BI e Marketing Digital. "
    "Quer saber mais sobre algum deles?"
)[:100]

SPEEDS = [1.0, 1.05, 1.08, 1.10, 1.15]
OUT_DIR = Path("/tmp/xtts_speed_benchmark")


def _wav_duration_sec(wav_bytes: bytes) -> float:
    pcm_bytes = max(0, len(wav_bytes) - 44)
    return pcm_bytes / 2 / 8000


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("COQUI_TOS_AGREED", "1")

    # Import after env — app reads COQUI_XTTS_SPEED per synthesis call
    sys.path.insert(0, "/app")
    from app import (  # type: ignore[import-untyped]
        _synthesize_to_wav,
        _wav_to_pcm_wav,
        get_tts,
    )

    speaker = os.getenv("COQUI_VOICE_SAMPLE", "")
    if not speaker or not Path(speaker).is_file():
        print(json.dumps({"error": f"speaker not found: {speaker!r}"}))
        return 1

    tts = get_tts()
    results: list[dict] = []

    for speed in SPEEDS:
        os.environ["COQUI_XTTS_SPEED"] = str(speed)
        out_path = str(OUT_DIR / f"speed_{speed:.2f}.wav")
        speaker_ms, synth_ms, _cached = _synthesize_to_wav(
            tts,
            text=SAMPLE_TEXT,
            speaker_path=speaker,
            language="pt",
            out_path=out_path,
        )
        pcm_wav = _wav_to_pcm_wav(out_path, 8000)
        duration_sec = _wav_duration_sec(pcm_wav)
        out_file = OUT_DIR / f"speed_{speed:.2f}_8k.wav"
        out_file.write_bytes(pcm_wav)
        results.append(
            {
                "speed": speed,
                "chars": len(SAMPLE_TEXT),
                "duration_sec": round(duration_sec, 2),
                "ms_per_char": round(duration_sec * 1000 / len(SAMPLE_TEXT), 1),
                "synth_ms": round(synth_ms, 0),
                "speaker_ms": round(speaker_ms, 0),
                "wav_8k": str(out_file),
            }
        )
        time.sleep(0.5)

    print(json.dumps({"text": SAMPLE_TEXT, "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
