import math
import struct

import numpy as np

from stem_mixer.spectrogram import _log_spectrogram, render_png


def test_png_header_and_size():
    image = render_png(np.zeros(1000, dtype=np.float32), 22050, (255, 176, 92), width=40, height=16)
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    assert image[12:16] == b"IHDR"
    width, height = struct.unpack(">II", image[16:24])
    assert (width, height) == (40, 16)


def test_sine_energy_sits_on_its_frequency_row():
    rate = 22050
    seconds = 2
    freq = 1000
    count = rate * seconds
    time = np.arange(count, dtype=np.float32) / rate
    samples = (0.6 * np.sin(2 * math.pi * freq * time)).astype(np.float32)
    height = 96
    norm = _log_spectrogram(samples, rate, width=80, height=height)
    profile = norm.mean(axis=1)
    peak = int(profile.argmax())
    # log scale from 40 Hz to Nyquist puts 1 kHz a bit above the middle.
    assert height * 0.45 < peak < height * 0.72
    assert profile[peak] > profile[2] + 0.25
    assert profile[peak] > profile[-2] + 0.15
