import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from stem_mixer.audio import AudioError
from stem_mixer.mix import clamp_gain, export_mix, mix_command
from wavutil import write_tone


def test_mix_command_keeps_a_plain_sum():
    command = mix_command(
        [(Path("vocals.wav"), 0.5), (Path("drums.wav"), 1.25)],
        Path("out.mp3"),
    )
    text = " ".join(command)
    assert "volume=0.500000" in text
    assert "volume=1.250000" in text
    assert "amix=inputs=2:normalize=0:duration=longest" in text


def test_single_stem_skips_amix(tmp_path):
    command = mix_command([(tmp_path / "vocals.wav", 0.8)], tmp_path / "out.mp3")
    assert "amix=" not in " ".join(command)
    assert "volume=0.800000" in " ".join(command)


def test_gain_is_clamped():
    assert clamp_gain(3) == 1.5
    assert clamp_gain(-0.2) == 0
    with pytest.raises(AudioError):
        clamp_gain(float("nan"))


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg no está instalado")
def test_export_gain_changes_loudness(tmp_path):
    tone = tmp_path / "tone.wav"
    write_tone(tone, freq=440, seconds=1.5, amp=0.5)
    loud = tmp_path / "loud.mp3"
    quiet = tmp_path / "quiet.mp3"
    export_mix([(tone, 1.0)], loud)
    export_mix([(tone, 0.5)], quiet)
    ratio = _rms(loud) / _rms(quiet)
    assert 1.6 < ratio < 2.5


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg no está instalado")
def test_export_rejects_silence(tmp_path):
    tone = tmp_path / "tone.wav"
    write_tone(tone, seconds=0.2)
    with pytest.raises(AudioError):
        export_mix([(tone, 0)], tmp_path / "mix.mp3")


def _rms(path):
    raw = subprocess.check_output(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-ac", "1", "-f", "f32le", "pipe:1"],
        stdin=subprocess.DEVNULL,
    )
    data = np.frombuffer(raw, dtype=np.float32)
    if data.size > 8000:
        data = data[4000:-4000]
    return float(np.sqrt(np.mean(np.square(data))))
