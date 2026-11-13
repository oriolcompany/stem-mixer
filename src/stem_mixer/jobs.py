"""On-disk jobs under %LOCALAPPDATA%\\StemMixer\\jobs."""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from pathlib import Path

_JOB_ID = re.compile(r"^[0-9a-f]{32}$")
_lock = threading.Lock()


def jobs_root() -> Path:
    env = (os.environ.get("STEM_MIXER_JOBS") or "").strip()
    if env:
        path = Path(env)
    else:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        path = base / "StemMixer" / "jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_dir(job_id: str) -> Path:
    if not _JOB_ID.fullmatch(job_id):
        raise KeyError(job_id)
    return jobs_root() / job_id


def write_status(job_id: str, **fields) -> dict:
    path = job_dir(job_id) / "status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        current: dict = {}
        if path.is_file():
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                current = {}
        current.update(fields)
        current["id"] = job_id
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
        return current


def read_status(job_id: str) -> dict:
    path = job_dir(job_id) / "status.json"
    if not path.is_file():
        raise FileNotFoundError(job_id)
    return json.loads(path.read_text(encoding="utf-8"))


def fail_interrupted() -> None:
    root = jobs_root()
    if not root.is_dir():
        return
    for folder in root.iterdir():
        if not folder.is_dir() or not _JOB_ID.fullmatch(folder.name):
            continue
        status_path = folder / "status.json"
        if not status_path.is_file():
            continue
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if status.get("status") == "running":
            write_status(
                folder.name,
                status="error",
                error="La separación se interrumpió. Vuelve a abrir el archivo.",
            )


def prune_old(max_age_seconds: float = 7 * 24 * 3600) -> None:
    root = jobs_root()
    now = time.time()
    for folder in root.iterdir():
        try:
            if folder.is_dir() and now - folder.stat().st_mtime > max_age_seconds:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            continue
