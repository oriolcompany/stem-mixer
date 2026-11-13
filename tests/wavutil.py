"""Tiny PCM fixtures for the mixer tests."""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path


def write_tone(
    path: Path,
    freq: float = 440,
    seconds: float = 1.0,
    amp: float = 0.4,
    rate: int = 44100,
) -> None:
    count = int(seconds * rate)
    frames = bytearray()
    for index in range(count):
        value = amp * math.sin(2 * math.pi * freq * index / rate)
        sample = int(max(-1.0, min(1.0, value)) * 32767)
        frames += struct.pack("<hh", sample, sample)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(frames)
