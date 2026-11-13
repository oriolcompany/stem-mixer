"""Log-frequency spectrogram rendered as a PNG, one image per stem."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

from .audio import run_ffmpeg

_N_FFT = 2048
_FMIN = 40.0


def read_mono(path: Path, sample_rate: int = 22050) -> np.ndarray:
    result = run_ffmpeg(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path.resolve()),
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "f32le",
            "pipe:1",
        ]
    )
    if not result.stdout:
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(result.stdout, dtype=np.float32).copy()


def render_png(
    samples: np.ndarray,
    sample_rate: int,
    color: tuple[int, int, int],
    width: int = 1200,
    height: int = 168,
) -> bytes:
    logged = _log_spectrogram(samples, sample_rate, width, height)
    rgb = _colorize(logged, color)
    return _encode_png(rgb)


def write_spectrogram(audio: Path, dest: Path, color: tuple[int, int, int]) -> None:
    samples = read_mono(audio)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(render_png(samples, 22050, color))


def hex_color(value: str) -> tuple[int, int, int]:
    raw = value.removeprefix("#")
    if len(raw) != 6:
        raise ValueError(value)
    return tuple(int(raw[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _log_spectrogram(
    samples: np.ndarray,
    sample_rate: int,
    width: int,
    height: int,
) -> np.ndarray:
    mag = _magnitudes(np.asarray(samples, dtype=np.float32), _N_FFT, width)
    binned = _log_frequency(mag, sample_rate, _N_FFT, height)
    frames = binned.shape[1]
    if frames == width:
        cols = binned
    elif frames <= 1:
        cols = np.repeat(binned, width, axis=1)
    else:
        index = np.linspace(0, frames - 1, width).astype(np.int32)
        cols = binned[:, index]
    logged = np.log10(cols + 1e-8)
    low, high = np.percentile(logged, [8, 99])
    if high <= low:
        return np.zeros_like(logged)
    return np.clip((logged - low) / (high - low), 0.0, 1.0)


def _magnitudes(samples: np.ndarray, n_fft: int, target_frames: int) -> np.ndarray:
    bins = n_fft // 2 + 1
    if samples.size == 0:
        return np.zeros((1, bins), dtype=np.float32)
    if samples.size < n_fft:
        samples = np.pad(samples, (0, n_fft - samples.size))
    samples = np.ascontiguousarray(samples, dtype=np.float32)
    hop = max(1, (samples.size - n_fft) // max(target_frames, 1))
    n_frames = 1 + (samples.size - n_fft) // hop
    window = np.hanning(n_fft).astype(np.float32)
    shape = (n_frames, n_fft)
    strides = (samples.strides[0] * hop, samples.strides[0])
    view = np.lib.stride_tricks.as_strided(samples, shape=shape, strides=strides)
    spectrum = np.fft.rfft(view * window, axis=1)
    return np.abs(spectrum).astype(np.float32)


def _log_frequency(mag: np.ndarray, sample_rate: int, n_fft: int, height: int) -> np.ndarray:
    n_bins = mag.shape[1]
    freqs = np.linspace(0, sample_rate / 2, n_bins)
    edges = np.geomspace(_FMIN, sample_rate / 2, height + 1)
    out = np.empty((height, mag.shape[0]), dtype=np.float32)
    for row in range(height):
        low = int(np.searchsorted(freqs, edges[row], side="left"))
        high = int(np.searchsorted(freqs, edges[row + 1], side="right"))
        low = min(max(low, 0), n_bins - 1)
        high = min(max(high, low + 1), n_bins)
        out[row] = mag[:, low:high].mean(axis=1)
    return out


def _colorize(norm: np.ndarray, color: tuple[int, int, int]) -> np.ndarray:
    background = np.array([14, 16, 20], dtype=np.float32)
    foreground = np.array(color, dtype=np.float32)
    power = np.clip(norm, 0.0, 1.0) ** 0.72
    peak = np.clip((norm - 0.78) / 0.22, 0.0, 1.0)
    rgb = background + (foreground - background) * power[..., None]
    white = np.array([255.0, 255.0, 255.0], dtype=np.float32)
    rgb = rgb + (white - rgb) * (peak[..., None] * 0.7)
    image = np.clip(rgb, 0, 255).astype(np.uint8)
    return image[::-1]


def _encode_png(rgb: np.ndarray) -> bytes:
    height, width, channels = rgb.shape
    if channels != 3:
        raise ValueError("El sonograma tiene que ser RGB")

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    raw = b"".join(b"\x00" + rgb[row].tobytes() for row in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )
