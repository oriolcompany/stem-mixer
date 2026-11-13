"""ffmpeg helpers shared by separation, spectrograms, and export."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class AudioError(RuntimeError):
    pass


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def run_ffmpeg(command: list[str]) -> subprocess.CompletedProcess[bytes]:
    if not ffmpeg_available():
        raise AudioError("Falta ffmpeg en el PATH")
    result = subprocess.run(command, capture_output=True, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        detail = (result.stderr or b"").decode("utf-8", "replace").strip()
        raise AudioError(detail[:400] or "ffmpeg ha fallado")
    return result


def to_pcm_wav(source: Path, dest: Path) -> None:
    """Rewrite a stem as 44.1 kHz stereo PCM so the browser can decode it."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source.resolve()),
            "-ac",
            "2",
            "-ar",
            "44100",
            "-c:a",
            "pcm_s16le",
            str(dest.resolve()),
        ]
    )
    if not dest.is_file() or dest.stat().st_size <= 0:
        raise AudioError(f"No se pudo convertir {source.name}")


def media_duration(path: Path) -> float:
    if shutil.which("ffprobe") is None:
        raise AudioError("Falta ffprobe en el PATH")
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path.resolve()),
        ],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        detail = (result.stderr or "").strip()[:300]
        raise AudioError(detail or "ffprobe ha fallado")
    try:
        return max(0.0, float(result.stdout.strip()))
    except ValueError as exc:
        raise AudioError(f"Duración ilegible: {result.stdout!r}") from exc
