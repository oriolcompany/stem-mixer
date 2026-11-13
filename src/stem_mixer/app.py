"""Local web mixer: separate an MP3, then play and export the stems."""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import threading
import time
import uuid
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import jobs
from .audio import AudioError, ffmpeg_available, media_duration
from .catalog import stem_payload
from .mix import export_mix
from .separate import SeparationError, model_name, separate_file, separation_available
from .spectrogram import hex_color, write_spectrogram

log = logging.getLogger("stem_mixer")

WEB_DIR = Path(__file__).resolve().parent / "web"
ALLOWED = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus"}
_UNSAFE_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')

app = FastAPI(title="Stem Mixer", docs_url=None, redoc_url=None)

_active_lock = threading.Lock()
_active: str | None = None


class ExportBody(BaseModel):
    gains: dict[str, float] = Field(default_factory=dict)


def _begin(job_id: str) -> bool:
    global _active
    with _active_lock:
        if _active is not None:
            return False
        _active = job_id
        return True


def _end(job_id: str) -> None:
    global _active
    with _active_lock:
        if _active == job_id:
            _active = None


def _load(job_id: str) -> dict:
    try:
        return jobs.read_status(job_id)
    except (KeyError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="No se encuentra esa mezcla") from None
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="El estado del trabajo está dañado") from None


def _display_name(filename: str | None) -> str:
    raw = Path(filename or "audio.mp3").name
    cleaned = _UNSAFE_NAME.sub(" ", raw).strip() or "audio.mp3"
    return cleaned[:180]


def _download_name(filename: str | None) -> str:
    stem = Path(_display_name(filename)).stem.strip() or "mezcla"
    return f"{stem[:80]}-mix.mp3"


async def _save(upload: UploadFile, dest: Path) -> int:
    total = 0
    with dest.open("wb") as handle:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            total += len(chunk)
    return total


def _run_job(job_id: str, audio: Path) -> None:
    last_at = 0.0
    last_phase = ""

    def on_progress(ratio: float, phase: str) -> None:
        nonlocal last_at, last_phase
        now = time.monotonic()
        if phase == last_phase and now - last_at < 0.3 and ratio < 0.99:
            return
        last_at = now
        last_phase = phase
        jobs.write_status(job_id, status="running", phase=phase, progress=round(ratio, 4))

    try:
        folder = jobs.job_dir(job_id)
        stem_ids = separate_file(audio, folder / "stems", on_progress=on_progress)
        spectro_dir = folder / "spectrograms"
        for index, stem_id in enumerate(stem_ids):
            jobs.write_status(
                job_id,
                status="running",
                phase="sonograma",
                progress=round(0.90 + 0.08 * index / max(len(stem_ids), 1), 4),
            )
            source = folder / "stems" / f"{stem_id}.wav"
            color = hex_color(stem_payload(stem_id)["color"])
            write_spectrogram(source, spectro_dir / f"{stem_id}.png", color)
        duration = max(media_duration(folder / "stems" / f"{stem_id}.wav") for stem_id in stem_ids)
        jobs.write_status(
            job_id,
            status="done",
            phase="listo",
            progress=1,
            stems=[stem_payload(stem_id) for stem_id in stem_ids],
            duration=round(duration, 3),
            error=None,
        )
    except (SeparationError, AudioError) as exc:
        log.warning("Trabajo %s: %s", job_id, exc)
        jobs.write_status(job_id, status="error", phase="error", error=str(exc))
    except Exception as exc:  # noqa: BLE001 — surface a short message, keep the traceback in the log
        log.exception("Trabajo %s ha fallado", job_id)
        jobs.write_status(job_id, status="error", phase="error", error=f"No se ha podido separar: {exc}")
    finally:
        _end(job_id)


@app.get("/api/health")
def health() -> dict:
    ready = separation_available()
    return {
        "ffmpeg": ffmpeg_available(),
        "separation": ready,
        "model": model_name(),
        "hint": None
        if ready
        else 'Para separar pistas: pip install -e ".[stems]" (o ".[stems-cpu]") y ffmpeg en el PATH.',
    }


@app.post("/api/jobs", status_code=202)
async def create_job(file: UploadFile = File(...)) -> dict:
    if not separation_available():
        raise HTTPException(
            status_code=503,
            detail='Falta el separador. Instálalo con pip install -e ".[stems]" y comprueba que ffmpeg está en el PATH.',
        )
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(status_code=400, detail="Usa un MP3, WAV, FLAC, M4A, OGG u OPUS")

    job_id = uuid.uuid4().hex
    if not _begin(job_id):
        raise HTTPException(status_code=409, detail="Ya hay una separación en curso")

    folder = jobs.jobs_root() / job_id
    dest = folder / f"input{suffix}"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        written = await _save(file, dest)
        if written <= 0:
            raise HTTPException(status_code=400, detail="El archivo está vacío")
        jobs.write_status(
            job_id,
            status="running",
            phase="preparando",
            progress=0.02,
            filename=_display_name(file.filename),
            stems=[],
            duration=None,
            error=None,
        )
    except HTTPException:
        _end(job_id)
        shutil.rmtree(folder, ignore_errors=True)
        raise
    except Exception as exc:  # noqa: BLE001
        _end(job_id)
        shutil.rmtree(folder, ignore_errors=True)
        log.exception("No se ha podido guardar la subida")
        raise HTTPException(status_code=500, detail="No se ha podido guardar el archivo") from exc

    threading.Thread(target=_run_job, args=(job_id, dest), daemon=True).start()
    return {"id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    return _load(job_id)


@app.get("/api/jobs/{job_id}/audio/{stem_id}")
def stem_audio(job_id: str, stem_id: str) -> FileResponse:
    path = _asset(job_id, stem_id, "audio")
    return FileResponse(path, media_type="audio/wav")


@app.get("/api/jobs/{job_id}/spectrogram/{stem_id}")
def stem_spectrogram(job_id: str, stem_id: str) -> FileResponse:
    path = _asset(job_id, stem_id, "spectrogram")
    return FileResponse(path, media_type="image/png")


@app.post("/api/jobs/{job_id}/export")
def export_job(job_id: str, body: ExportBody) -> FileResponse:
    status = _load(job_id)
    if status.get("status") != "done":
        raise HTTPException(status_code=409, detail="La separación todavía no ha terminado")
    stems = status.get("stems") or []
    if not stems:
        raise HTTPException(status_code=409, detail="Esta mezcla no tiene pistas")
    pairs = []
    folder = jobs.job_dir(job_id) / "stems"
    for stem in stems:
        stem_id = stem["id"]
        pairs.append((folder / f"{stem_id}.wav", body.gains.get(stem_id, 1.0)))
    target = jobs.job_dir(job_id) / "mix.mp3"
    try:
        export_mix(pairs, target)
    except AudioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(
        target,
        media_type="audio/mpeg",
        filename=_download_name(status.get("filename")),
    )


def _asset(job_id: str, stem_id: str, kind: str) -> Path:
    status = _load(job_id)
    known = {stem["id"] for stem in status.get("stems") or [] if isinstance(stem, dict) and "id" in stem}
    if stem_id not in known:
        raise HTTPException(status_code=404, detail="Pista desconocida")
    if kind == "audio":
        path = jobs.job_dir(job_id) / "stems" / f"{stem_id}.wav"
    else:
        path = jobs.job_dir(job_id) / "spectrograms" / f"{stem_id}.png"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return path


@app.middleware("http")
async def no_cache_assets(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".js", ".css", ".html")):
        response.headers["Cache-Control"] = "no-store"
    return response


if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Stem Mixer, separación y mezcla local")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8780)
    parser.add_argument("--open", dest="open_browser", action="store_true", default=True)
    parser.add_argument("--no-open", dest="open_browser", action="store_false")
    args = parser.parse_args()
    if not WEB_DIR.is_dir():
        raise SystemExit(f"No está la interfaz en {WEB_DIR}")
    jobs.fail_interrupted()
    jobs.prune_old()
    url = f"http://{args.host}:{args.port}"
    log.info("Stem Mixer en %s (modelo %s)", url, model_name())
    if args.open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
