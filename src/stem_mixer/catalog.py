"""Stem ids produced by htdemucs, in mixer order."""

from __future__ import annotations

from pathlib import Path

# Same four-stem layout karaoke-party gets from htdemucs. A two-stem model
# falls back to vocals + instrumental.
STEMS: dict[str, dict[str, str]] = {
    "vocals": {"label": "Voces", "color": "#ffb05c"},
    "drums": {"label": "Batería", "color": "#ff6a5c"},
    "bass": {"label": "Bajo", "color": "#5ec8be"},
    "other": {"label": "Otros", "color": "#b496ff"},
    "instrumental": {"label": "Instrumental", "color": "#8aa8c8"},
}

STEM_ORDER = ("vocals", "drums", "bass", "other", "instrumental")

_EXACT = {
    "stem_vocals": "vocals",
    "vocals": "vocals",
    "stem_drums": "drums",
    "drums": "drums",
    "stem_bass": "bass",
    "bass": "bass",
    "stem_other": "other",
    "other": "other",
    "stem_instrumental": "instrumental",
    "instrumental": "instrumental",
}


def classify_name(path: Path) -> str | None:
    stem = path.stem.lower()
    if stem in _EXACT:
        return _EXACT[stem]
    name = path.name.lower()
    for key in ("vocals", "drums", "bass", "instrumental", "other"):
        if f"({key})" in name or stem.endswith(f"_{key}") or stem.endswith(f"-{key}"):
            return key
    return None


def stem_payload(stem_id: str) -> dict[str, str]:
    meta = STEMS[stem_id]
    return {"id": stem_id, "label": meta["label"], "color": meta["color"]}
