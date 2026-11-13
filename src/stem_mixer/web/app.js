const openButton = document.getElementById("openFile");
const fileInput = document.getElementById("file");
const drop = document.getElementById("drop");
const progress = document.getElementById("progress");
const progressLabel = document.getElementById("progressLabel");
const progressPct = document.getElementById("progressPct");
const progressBar = document.getElementById("progressBar");
const studio = document.getElementById("studio");
const song = document.getElementById("song");
const playButton = document.getElementById("play");
const timeLabel = document.getElementById("time");
const durationLabel = document.getElementById("duration");
const scrub = document.getElementById("scrub");
const scrubFill = document.getElementById("scrubFill");
const tracks = document.getElementById("tracks");
const exportButton = document.getElementById("export");
const exportStatus = document.getElementById("exportStatus");
const errorBox = document.getElementById("error");
const banner = document.getElementById("banner");

const PHASES = {
  preparando: "Preparando el archivo",
  modelo: "Cargando el modelo de separación",
  separando: "Separando las pistas",
  codificando: "Guardando las pistas",
  sonograma: "Calculando sonogramas",
  listo: "Listo",
  error: "Error",
};

let job = null;
let pollToken = 0;
let ctx = null;
let buffers = {};
let gains = {};
let active = [];
let decodedFor = "";
let decodePromise = null;
let playing = false;
let anchorOffset = 0;
let anchorCtx = 0;
let duration = 0;
const volumes = {};
const muted = {};

openButton.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => {
  const file = fileInput.files && fileInput.files[0];
  fileInput.value = "";
  if (file) upload(file);
});

window.addEventListener("dragover", (event) => {
  event.preventDefault();
  document.body.classList.add("drag");
});
window.addEventListener("dragleave", () => document.body.classList.remove("drag"));
window.addEventListener("drop", (event) => {
  event.preventDefault();
  document.body.classList.remove("drag");
  const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
  if (file) upload(file);
});

playButton.addEventListener("click", () => {
  toggle().catch((error) => showError(error.message || "No se ha podido reproducir"));
});
exportButton.addEventListener("click", () => {
  exportMix().catch((error) => setExport(error.message || "No se ha podido exportar", "bad"));
});
bindSeek(scrub);

window.addEventListener("keydown", (event) => {
  if (!job || job.status !== "done") return;
  if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
  if (event.code === "Space" && event.target instanceof HTMLElement && event.target.closest("button")) return;
  if (event.code === "Space") {
    event.preventDefault();
    toggle().catch((error) => showError(error.message || "No se ha podido reproducir"));
  } else if (event.code === "ArrowRight") {
    event.preventDefault();
    seekTo(position() + 5);
  } else if (event.code === "ArrowLeft") {
    event.preventDefault();
    seekTo(position() - 5);
  }
});

loadHealth();
const initial = new URLSearchParams(location.search).get("job");
if (initial) watch(initial);

async function loadHealth() {
  try {
    const data = await api("/api/health");
    if (data.hint) {
      banner.hidden = false;
      banner.textContent = data.hint;
    }
  } catch {
    banner.hidden = false;
    banner.textContent = "No se ha podido contactar con el servidor.";
  }
}

async function upload(file) {
  clearError();
  setExport("");
  stopPlayback(true);
  const body = new FormData();
  body.append("file", file, file.name);
  openButton.disabled = true;
  showProgress({ phase: "preparando", progress: 0.02 });
  try {
    const created = await api("/api/jobs", { method: "POST", body });
    const url = new URL(location.href);
    url.searchParams.set("job", created.id);
    history.replaceState(null, "", url);
    await watch(created.id);
  } catch (error) {
    showError(error.message || "No se ha podido abrir el archivo");
    progress.hidden = true;
  } finally {
    openButton.disabled = false;
  }
}

async function watch(id) {
  const token = ++pollToken;
  stopPlayback(true);
  while (token === pollToken) {
    let current;
    try {
      current = await api(`/api/jobs/${id}`);
    } catch (error) {
      showError(error.message || "No se encuentra esa mezcla");
      return;
    }
    job = current;
    if (current.status === "done") {
      showStudio(current);
      return;
    }
    if (current.status === "error") {
      progress.hidden = true;
      studio.hidden = true;
      drop.hidden = false;
      showError(current.error || "La separación ha fallado");
      return;
    }
    showProgress(current);
    await sleep(700);
  }
}

function showProgress(current) {
  drop.hidden = true;
  studio.hidden = true;
  progress.hidden = false;
  const phase = PHASES[current.phase] || "Trabajando";
  progressLabel.textContent = phase;
  const pct = Math.round(Math.max(0, Math.min(1, Number(current.progress) || 0)) * 100);
  progressPct.textContent = `${pct}%`;
  progressBar.style.width = `${pct}%`;
}

function showStudio(current) {
  clearError();
  drop.hidden = true;
  progress.hidden = true;
  studio.hidden = false;
  song.textContent = current.filename || "Mezcla";
  document.title = `${song.textContent} · Stem Mixer`;
  duration = Number(current.duration) || 0;
  durationLabel.textContent = formatTime(duration);
  if (decodedFor !== current.id) {
    buffers = {};
    decodePromise = null;
    decodedFor = "";
    anchorOffset = 0;
    playing = false;
  }
  renderTracks(current);
  draw();
}

function renderTracks(current) {
  tracks.replaceChildren();
  for (const stem of current.stems || []) {
    if (volumes[stem.id] == null) volumes[stem.id] = 1;
    if (muted[stem.id] == null) muted[stem.id] = false;
    const color = safeColor(stem.color);

    const article = document.createElement("article");
    article.className = "track";
    article.style.setProperty("--stem", color);

    const head = document.createElement("div");
    head.className = "track-head";
    const title = document.createElement("h3");
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    title.append(swatch, document.createTextNode(stem.label || stem.id));

    const vol = document.createElement("label");
    vol.className = "vol";
    const volName = document.createElement("span");
    volName.textContent = "Volumen";
    const slider = document.createElement("input");
    slider.type = "range";
    slider.min = "0";
    slider.max = "150";
    slider.value = String(Math.round(volumes[stem.id] * 100));
    slider.setAttribute("aria-label", `Volumen de ${stem.label || stem.id}`);
    const out = document.createElement("output");
    out.textContent = `${slider.value}%`;
    slider.addEventListener("input", () => {
      volumes[stem.id] = Number(slider.value) / 100;
      out.textContent = `${slider.value}%`;
      applyGain(stem.id);
      article.classList.toggle("is-silent", gainOf(stem.id) === 0);
    });
    vol.append(volName, slider, out);

    const mute = document.createElement("button");
    mute.type = "button";
    mute.className = "mute";
    mute.textContent = "Mute";
    mute.setAttribute("aria-pressed", muted[stem.id] ? "true" : "false");
    mute.addEventListener("click", () => {
      muted[stem.id] = !muted[stem.id];
      mute.setAttribute("aria-pressed", muted[stem.id] ? "true" : "false");
      applyGain(stem.id);
      article.classList.toggle("is-silent", gainOf(stem.id) === 0);
    });

    head.append(title, vol, mute);

    const spec = document.createElement("div");
    spec.className = "spec";
    const img = document.createElement("img");
    img.alt = `Sonograma de ${stem.label || stem.id}`;
    img.draggable = false;
    img.src = `/api/jobs/${current.id}/spectrogram/${encodeURIComponent(stem.id)}`;
    const playhead = document.createElement("div");
    playhead.className = "playhead";
    spec.append(img, playhead);
    bindSeek(spec);

    article.append(head, spec);
    article.classList.toggle("is-silent", gainOf(stem.id) === 0);
    tracks.append(article);
  }
}

function bindSeek(element) {
  element.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const wasPlaying = playing;
    element.setPointerCapture(event.pointerId);
    previewSeek(ratioFromEvent(event, element));
    function move(next) {
      previewSeek(ratioFromEvent(next, element));
    }
    function up(next) {
      element.removeEventListener("pointermove", move);
      element.removeEventListener("pointerup", up);
      previewSeek(ratioFromEvent(next, element));
      if (wasPlaying) {
        ensureAudio()
          .then(() => startSources())
          .catch((error) => showError(error.message || "No se ha podido reproducir"));
      }
    }
    element.addEventListener("pointermove", move);
    element.addEventListener("pointerup", up);
  });
}

async function toggle() {
  if (!job || job.status !== "done") return;
  await ensureAudio();
  if (playing) {
    anchorOffset = position();
    stopSources();
    playing = false;
    draw();
  } else {
    startSources();
  }
  updatePlayButton();
}

async function ensureAudio() {
  if (!job) return;
  if (!ctx) ctx = new AudioContext();
  if (ctx.state === "suspended") await ctx.resume();
  if (decodedFor === job.id) return;
  const current = job;
  if (!decodePromise) {
    const task = decodeAll(current);
    decodePromise = task;
    task.then(
      () => {
        if (decodePromise === task && decodedFor !== current.id) decodePromise = null;
      },
      () => {
        if (decodePromise === task) decodePromise = null;
      },
    );
  }
  await decodePromise;
}

async function decodeAll(current) {
  playButton.disabled = true;
  playButton.textContent = "Cargando…";
  try {
    const next = {};
    await Promise.all(
      (current.stems || []).map(async (stem) => {
        const response = await fetch(`/api/jobs/${current.id}/audio/${encodeURIComponent(stem.id)}`);
        if (!response.ok) throw new Error(`No se ha podido leer ${stem.label || stem.id}`);
        const copy = (await response.arrayBuffer()).slice(0);
        next[stem.id] = await ctx.decodeAudioData(copy);
      }),
    );
    if (!job || job.id !== current.id) return;
    buffers = next;
    decodedFor = current.id;
    const lengths = Object.values(buffers).map((buffer) => buffer.duration);
    if (lengths.length) duration = Math.max(...lengths);
    durationLabel.textContent = formatTime(duration);
    ensureGains();
  } finally {
    playButton.disabled = false;
    updatePlayButton();
  }
}

function ensureGains() {
  for (const stem of job.stems || []) {
    let node = gains[stem.id];
    if (!node) {
      node = ctx.createGain();
      node.connect(ctx.destination);
      gains[stem.id] = node;
    }
    node.gain.value = gainOf(stem.id);
  }
}

function applyGain(stemId) {
  const node = gains[stemId];
  if (node) node.gain.value = gainOf(stemId);
}

function gainOf(stemId) {
  if (muted[stemId]) return 0;
  const value = volumes[stemId];
  return Number.isFinite(value) ? value : 1;
}

function startSources() {
  if (!ctx || decodedFor !== (job && job.id)) return;
  if (anchorOffset >= duration - 0.05) anchorOffset = 0;
  stopSources();
  anchorCtx = ctx.currentTime;
  const offset = anchorOffset;
  for (const stem of job.stems || []) {
    const buffer = buffers[stem.id];
    if (!buffer || offset >= buffer.duration - 0.001) continue;
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(gains[stem.id]);
    source.start(anchorCtx, offset);
    active.push(source);
  }
  if (!active.length) return;
  playing = true;
  updatePlayButton();
  requestAnimationFrame(tick);
}

function stopSources() {
  for (const source of active) {
    try {
      source.onended = null;
      source.stop();
    } catch {
      /* already stopped */
    }
  }
  active = [];
}

function stopPlayback(reset) {
  stopSources();
  playing = false;
  if (reset) {
    anchorOffset = 0;
    buffers = {};
    decodePromise = null;
    decodedFor = "";
  }
  updatePlayButton();
}

function tick() {
  if (!playing) return;
  if (position() >= duration - 0.03) {
    stopSources();
    playing = false;
    anchorOffset = duration;
    draw();
    updatePlayButton();
    return;
  }
  draw();
  requestAnimationFrame(tick);
}

function seekTo(time) {
  const was = playing;
  previewSeek(time / Math.max(duration, 0.001));
  if (was) {
    ensureAudio()
      .then(() => startSources())
      .catch((error) => showError(error.message || "No se ha podido reproducir"));
  }
}

function previewSeek(ratio) {
  const span = Number.isFinite(duration) ? duration : 0;
  anchorOffset = clamp(ratio, 0, 1) * span;
  stopSources();
  playing = false;
  draw();
  updatePlayButton();
}

function ratioFromEvent(event, element) {
  const rect = element.getBoundingClientRect();
  if (rect.width <= 0) return 0;
  return clamp((event.clientX - rect.left) / rect.width, 0, 1);
}

function position() {
  if (!playing || !ctx) return anchorOffset;
  return anchorOffset + (ctx.currentTime - anchorCtx);
}

function draw() {
  const at = clamp(position(), 0, duration || 0);
  const ratio = duration > 0 ? at / duration : 0;
  for (const head of tracks.querySelectorAll(".playhead")) {
    head.style.left = `${ratio * 100}%`;
  }
  scrubFill.style.width = `${ratio * 100}%`;
  scrub.setAttribute("aria-valuenow", String(Math.round(ratio * 100)));
  scrub.setAttribute("aria-valuemax", "100");
  timeLabel.textContent = formatTime(at);
}

function updatePlayButton() {
  if (playButton.disabled) return;
  playButton.textContent = playing ? "Pausa" : "Reproducir";
  playButton.setAttribute("aria-label", playButton.textContent);
}

async function exportMix() {
  if (!job || job.status !== "done") return;
  exportButton.disabled = true;
  setExport("Exportando la mezcla…", "");
  try {
    const gains = {};
    for (const stem of job.stems || []) gains[stem.id] = gainOf(stem.id);
    const response = await fetch(`/api/jobs/${job.id}/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ gains }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      const detail = typeof data.detail === "string" ? data.detail : "No se ha podido exportar";
      throw new Error(detail);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = mixFilename(job.filename);
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    setExport("Mezcla descargada.", "ok");
  } finally {
    exportButton.disabled = false;
  }
}

function mixFilename(filename) {
  const base = (filename || "mezcla").replace(/\.[^.]+$/, "").trim() || "mezcla";
  return `${base}-mix.mp3`;
}

function showError(message) {
  errorBox.hidden = false;
  errorBox.textContent = message;
}

function clearError() {
  errorBox.hidden = true;
  errorBox.textContent = "";
}

function setExport(message, kind) {
  exportStatus.textContent = message;
  exportStatus.className = kind || "";
}

function safeColor(value) {
  return /^#[0-9a-fA-F]{6}$/.test(value || "") ? value : "#ffb05c";
}

function formatTime(seconds) {
  const whole = Math.max(0, Math.floor(Number(seconds) || 0));
  const minutes = Math.floor(whole / 60);
  const remain = whole % 60;
  return `${minutes}:${String(remain).padStart(2, "0")}`;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function api(url, options) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : `Error ${response.status}`;
    throw new Error(detail);
  }
  return data;
}
