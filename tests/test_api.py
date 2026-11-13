import json
import threading

import pytest
from fastapi.testclient import TestClient

from stem_mixer import app as app_module
from stem_mixer import jobs
from stem_mixer.catalog import stem_payload
from stem_mixer.spectrogram import render_png
from wavutil import write_tone

import numpy as np


@pytest.fixture(autouse=True)
def isolated_jobs(tmp_path, monkeypatch):
    monkeypatch.setenv("STEM_MIXER_JOBS", str(tmp_path / "jobs"))
    yield
    with app_module._active_lock:
        app_module._active = None


@pytest.fixture
def client():
    return TestClient(app_module.app)


def test_health_reports_ffmpeg(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ffmpeg"] is True
    assert body["model"] == "htdemucs.yaml"
    assert "separation" in body


def test_rejects_unknown_extension(client, monkeypatch):
    monkeypatch.setattr(app_module, "separation_available", lambda: True)
    response = client.post("/api/jobs", files={"file": ("notes.txt", b"hola", "text/plain")})
    assert response.status_code == 400


def test_missing_separator_is_503(client, monkeypatch):
    monkeypatch.setattr(app_module, "separation_available", lambda: False)
    response = client.post("/api/jobs", files={"file": ("song.mp3", b"not-empty", "audio/mpeg")})
    assert response.status_code == 503


def test_second_upload_is_rejected_while_one_runs(client, monkeypatch):
    monkeypatch.setattr(app_module, "separation_available", lambda: True)

    class Idle(threading.Thread):
        def start(self):
            return None

    monkeypatch.setattr(app_module.threading, "Thread", Idle)
    first = client.post("/api/jobs", files={"file": ("song.mp3", b"not-empty", "audio/mpeg")})
    second = client.post("/api/jobs", files={"file": ("other.mp3", b"not-empty", "audio/mpeg")})
    assert first.status_code == 202
    assert second.status_code == 409


def test_spectrogram_audio_and_export(client):
    job_id = "ab" * 16
    folder = jobs.jobs_root() / job_id
    stems = folder / "stems"
    stems.mkdir(parents=True)
    write_tone(stems / "vocals.wav", freq=440, seconds=0.6, amp=0.5)
    write_tone(stems / "drums.wav", freq=120, seconds=0.6, amp=0.4)
    images = folder / "spectrograms"
    images.mkdir()
    png = render_png(np.zeros(800, dtype=np.float32), 22050, (255, 106, 92), width=24, height=12)
    for name in ("vocals", "drums"):
        (images / f"{name}.png").write_bytes(png)
    jobs.write_status(
        job_id,
        status="done",
        phase="listo",
        progress=1,
        filename="demo.mp3",
        stems=[stem_payload("vocals"), stem_payload("drums")],
        duration=0.6,
        error=None,
    )

    status = client.get(f"/api/jobs/{job_id}")
    assert status.status_code == 200
    assert [item["id"] for item in status.json()["stems"]] == ["vocals", "drums"]

    image = client.get(f"/api/jobs/{job_id}/spectrogram/vocals")
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/png")
    assert image.content.startswith(b"\x89PNG")

    audio = client.get(f"/api/jobs/{job_id}/audio/drums")
    assert audio.status_code == 200
    assert audio.headers["content-type"].startswith("audio/wav")

    missing = client.get(f"/api/jobs/{job_id}/audio/bass")
    assert missing.status_code == 404

    exported = client.post(f"/api/jobs/{job_id}/export", json={"gains": {"vocals": 1, "drums": 0.4}})
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("audio/mpeg")
    assert exported.content[:3] == b"ID3" or exported.content[0] == 0xFF
    assert "demo-mix.mp3" in exported.headers["content-disposition"]

    silent = client.post(f"/api/jobs/{job_id}/export", json={"gains": {"vocals": 0, "drums": 0}})
    assert silent.status_code == 400
    assert "volumen" in silent.json()["detail"].lower()


def test_ui_is_served(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "Stem Mixer" in page.text
    script = client.get("/app.js")
    assert script.status_code == 200
    assert "Exportar" in script.text or "export" in script.text
    assert json.loads(client.get("/api/health").text)["model"]
