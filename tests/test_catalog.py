from pathlib import Path

from stem_mixer.catalog import classify_name


def test_classify_safe_stem_names():
    assert classify_name(Path("stem_vocals.wav")) == "vocals"
    assert classify_name(Path("stem_drums.wav")) == "drums"
    assert classify_name(Path("stem_bass.wav")) == "bass"
    assert classify_name(Path("stem_other.wav")) == "other"
    assert classify_name(Path("stem_instrumental.wav")) == "instrumental"


def test_classify_audio_separator_default_names():
    assert classify_name(Path("input_(Vocals)_htdemucs.wav")) == "vocals"
    assert classify_name(Path("input_(Drums)_htdemucs.wav")) == "drums"
    assert classify_name(Path("notes.wav")) is None
