# Stem Mixer

Programa local para separar un MP3 en pistas (voces, batería, bajo y el resto), escucharlas sobre un sonograma y exportar la mezcla a MP3.

La separación usa el mismo camino que karaoke-party: [`audio-separator`](https://github.com/nomadkaraoke/python-audio-separator) con el modelo Demucs `htdemucs`. Si Karaoke Party ya descargó los pesos, se reutilizan.

## Requisitos

- Python 3.11+
- [ffmpeg](https://ffmpeg.org) en el PATH (incluye ffprobe)
- Para separar: el extra `stems` (GPU) o `stems-cpu`

## Instalación

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[stems]"
python -m stem_mixer
```

Sin tarjeta NVIDIA:

```powershell
pip install -e ".[stems-cpu]"
```

En esta máquina, el entorno de karaoke-party ya tiene Demucs y ffmpeg. `Stem Mixer.bat` lo usa si el `.venv` local todavía no tiene el separador.

La app abre `http://127.0.0.1:8780`.

## Otro ordenador

No conviene un `.exe` único. PyTorch y CUDA pesan varios GB y las DLL de la GPU se rompen al congelarlas con PyInstaller. Karaoke Party hace lo mismo: el ejecutable no lleva Demucs; el programa se instala en un entorno de Python.

En el otro PC (Windows 10/11, 64 bits) basta con copiar esta carpeta, sin `.venv`, `.git` ni `.preview-jobs`, y abrir `Stem Mixer.bat`. Hace falta internet esa primera vez.

El arranque comprueba Python y ffmpeg:

- Si falta Python, instala Python 3.12 solo para el usuario (con winget o, si no está, con el instalador oficial). No hace falta marcarlo en el PATH a mano.
- Si falta ffmpeg, descarga una copia dentro de `tools\ffmpeg` y la usa desde ahí.
- Después crea `.venv` y descarga PyTorch. Con GPU NVIDIA instala la versión CUDA (unos 3 GB). Sin GPU, la versión CPU, que separa mucho más despacio.

El modelo Demucs (~80 MB) se descarga en la primera canción.

Para no repetir esa descarga, copia también `%LOCALAPPDATA%\KaraokeParty\stem-models` o `%LOCALAPPDATA%\StemMixer\models`. Hace falta conexión a internet solo en esa primera instalación, y los drivers NVIDIA al día si se usa la GPU.

## Uso

1. Suelta un MP3 (también vale WAV, FLAC, M4A, OGG u OPUS).
2. Espera a que termine la separación. La primera vez puede descargar el modelo.
3. Cada pista muestra su sonograma. Clic o arrastre para saltar. Espacio reproduce o pausa. Las flechas saltan 5 segundos.
4. Ajusta el volumen de cada pista (0–150 %) o pulsa Mute.
5. **Exportar mezcla MP3** guarda la suma con esos volúmenes.

Con las cuatro pistas al 100 % la suma reconstruye la mezcla de Demucs (sin normalizar hacia abajo).

## Variables

| Variable | Efecto |
| --- | --- |
| `STEM_MIXER_MODEL` | Archivo de modelo de audio-separator. Por defecto `htdemucs.yaml`. |
| `STEM_MIXER_MODELS` | Carpeta de pesos. Si no se indica y Karaoke Party ya tiene el modelo, se usa esa caché. |
| `STEM_MIXER_JOBS` | Carpeta de trabajos. Por defecto `%LOCALAPPDATA%\StemMixer\jobs`. |
| `STEM_MIXER_AUTOCAST` | `1` activa autocast en la separación. |
