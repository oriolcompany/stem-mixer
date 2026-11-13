"""Vocal / drums / bass / other separation.

This follows karaoke-party: `audio-separator` with the UVR Demucs model
`htdemucs`, weights downloaded once (or reused from Karaoke Party's cache),
and ffmpeg afterwards. Each stem is kept on its own so the mixer can solo it.
"""

from __future__ import annotations

import importlib.util
import inspect
import os
import shutil
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from .audio import AudioError, ffmpeg_available, to_pcm_wav
from .catalog import STEM_ORDER, classify_name

DEFAULT_MODEL = (os.environ.get("STEM_MIXER_MODEL") or "").strip() or "htdemucs.yaml"

# ASCII names. audio-separator otherwise embeds the song title in every file,
# and on Windows that breaks the later ffmpeg step.
_SAFE_STEM_NAMES = {
    "Vocals": "stem_vocals",
    "Instrumental": "stem_instrumental",
    "Bass": "stem_bass",
    "Drums": "stem_drums",
    "Other": "stem_other",
}

_SEPARATE_FROM = 0.12
_SEPARATE_TO = 0.82

_separator = None
_separator_model: str | None = None
_separator_lock = threading.Lock()
_separation_lock = threading.Lock()


class SeparationError(AudioError):
    pass


def model_name() -> str:
    return DEFAULT_MODEL


def separation_available() -> bool:
    return importlib.util.find_spec("audio_separator") is not None and ffmpeg_available()


def scratch_dir() -> Path:
    """Initial separator output. Each run overrides this before separating."""
    path = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "StemMixer" / "scratch"
    path.mkdir(parents=True, exist_ok=True)
    return path


def models_dir() -> Path:
    env = (os.environ.get("STEM_MIXER_MODELS") or "").strip()
    if env:
        path = Path(env)
        path.mkdir(parents=True, exist_ok=True)
        return path
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    local = base / "StemMixer" / "models"
    local.mkdir(parents=True, exist_ok=True)
    if _has_weights(local):
        return local
    karaoke = base / "KaraokeParty" / "stem-models"
    if karaoke.is_dir() and _has_weights(karaoke):
        return karaoke
    return local


def separate_file(
    audio_path: Path,
    dest_dir: Path,
    on_progress: Callable[[float, str], None] | None = None,
) -> list[str]:
    """Write `dest_dir/{stem}.wav` and return stem ids in mixer order."""
    if not audio_path.is_file():
        raise SeparationError(f"No existe el archivo: {audio_path}")
    if not ffmpeg_available():
        raise SeparationError("Falta ffmpeg en el PATH")
    if importlib.util.find_spec("audio_separator") is None:
        raise SeparationError('Falta el separador. Instálalo con: pip install -e ".[stems]"')

    def report(ratio: float, phase: str) -> None:
        if on_progress is None:
            return
        try:
            on_progress(max(0.0, min(1.0, ratio)), phase)
        except Exception:  # noqa: BLE001 — progress must never abort separation
            pass

    dest_dir.mkdir(parents=True, exist_ok=True)
    with _separation_lock:
        report(0.04, "modelo")
        separator = _get_separator()
        run_dir = dest_dir / f"run-{uuid.uuid4().hex}"
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            _use_output_dir(separator, run_dir)
            staged = _stage_input(audio_path, run_dir)
            report(_SEPARATE_FROM, "separando")
            with _demucs_progress(report):
                produced = separator.separate(
                    str(staged),
                    custom_output_names=dict(_SAFE_STEM_NAMES),
                )
            outputs = _collect_wavs(produced, run_dir)
            classified = _classify(outputs)
            if not classified:
                listing = ", ".join(path.name for path in outputs) or "(vacío)"
                raise SeparationError(f"El separador no ha generado pistas reconocibles: {listing}")
            report(0.86, "codificando")
            written: list[str] = []
            for stem_id in STEM_ORDER:
                source = classified.get(stem_id)
                if source is None:
                    continue
                to_pcm_wav(source, dest_dir / f"{stem_id}.wav")
                written.append(stem_id)
            if not written:
                raise SeparationError("No se ha podido guardar ninguna pista")
            return written
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)


def _has_weights(path: Path) -> bool:
    patterns = ("*.th", "*.ckpt", "*.onnx", "*.pth")
    return any(any(path.glob(pattern)) for pattern in patterns)


def _stage_input(audio_path: Path, run_dir: Path) -> Path:
    suffix = audio_path.suffix.lower()
    if suffix not in {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus"}:
        suffix = ".mp3"
    staged = run_dir / f"input{suffix}"
    shutil.copy2(audio_path, staged)
    return staged


def _use_output_dir(separator, folder: Path) -> None:
    """The loaded model keeps its own copy of the output directory."""
    separator.output_dir = str(folder)
    model = getattr(separator, "model_instance", None)
    if model is not None:
        model.output_dir = str(folder)


def _get_separator():
    global _separator, _separator_model
    from audio_separator.separator import Separator

    with _separator_lock:
        if _separator is None or _separator_model != DEFAULT_MODEL:
            separator = Separator(
                log_level=40,
                output_dir=str(scratch_dir()),
                output_format="WAV",
                model_file_dir=str(models_dir()),
                use_autocast=(os.environ.get("STEM_MIXER_AUTOCAST") or "").strip()
                not in {"", "0", "false"},
            )
            separator.load_model(model_filename=DEFAULT_MODEL)
            _separator = separator
            _separator_model = DEFAULT_MODEL
        return _separator


@contextmanager
def _demucs_progress(report: Callable[[float, str], None]) -> Iterator[None]:
    """Forward Demucs' per-chunk progress. A no-op if that hook disappears."""
    try:
        from audio_separator.separator.architectures import demucs_separator

        original = demucs_separator.apply_model
        supported = "set_progress_bar" in inspect.signature(original).parameters
    except Exception:  # noqa: BLE001 — progress must never block separation
        yield
        return
    if not supported:
        yield
        return

    def on_chunk(_base: float, value: float) -> None:
        done = min(1.0, max(0.0, float(value) / 0.8))
        report(_SEPARATE_FROM + done * (_SEPARATE_TO - _SEPARATE_FROM), "separando")

    def with_progress(*args, **kwargs):
        if kwargs.get("set_progress_bar") is None:
            kwargs["set_progress_bar"] = on_chunk
        return original(*args, **kwargs)

    demucs_separator.apply_model = with_progress
    try:
        yield
    finally:
        demucs_separator.apply_model = original


def _collect_wavs(produced: list | None, folder: Path) -> list[Path]:
    on_disk = {
        path.name.lower(): path
        for path in folder.glob("*.wav")
        if path.is_file() and path.stat().st_size > 0 and not path.stem.lower().startswith("input")
    }
    ordered: list[Path] = []
    seen: set[str] = set()
    for item in produced or []:
        name = Path(str(item)).name.lower()
        path = on_disk.get(name)
        if path is not None and name not in seen:
            ordered.append(path)
            seen.add(name)
    for name, path in sorted(on_disk.items()):
        if name not in seen:
            ordered.append(path)
    return ordered


def _classify(paths: list[Path]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in paths:
        kind = classify_name(path)
        if kind is not None and kind not in found:
            found[kind] = path
    return found
