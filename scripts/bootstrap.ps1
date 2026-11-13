# Prepares Stem Mixer on a clean Windows PC and then starts it.
# Installs a per-user Python 3.12 and a local ffmpeg when they are missing.
param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [switch]$DetectOnly
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
Set-Location -LiteralPath $RepoRoot

function Refresh-EnvPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($machine -or $user) {
        $env:Path = "$user;$machine"
    }
}

function Test-RealCommand([string]$Name) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $cmd) { return $null }
    if ($cmd.Source -like "*\WindowsApps\*") { return $null }
    return $cmd.Source
}

function Test-PythonExe([string]$Exe) {
    if (-not $Exe) { return $false }
    $Exe = $Exe.Trim()
    # The store alias opens the Microsoft Store. A real install lives in a subfolder.
    if ($Exe -match '\\WindowsApps\\python(3(\.\d+)?)?\.exe$') { return $false }
    if (-not (Test-Path -LiteralPath $Exe)) { return $false }
    & $Exe -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
    return $LASTEXITCODE -eq 0
}

function Find-Python {
    Refresh-EnvPath
    $candidates = [System.Collections.Generic.List[string]]::new()
    foreach ($minor in 12, 13, 11, 14) {
        $candidates.Add("$env:LocalAppData\Programs\Python\Python$minor\python.exe")
        $candidates.Add("$env:ProgramFiles\Python$minor\python.exe")
    }
    $onPath = @(where.exe python 2>$null)
    foreach ($exe in $onPath) { $candidates.Add($exe) }
    foreach ($candidate in $candidates) {
        if (Test-PythonExe $candidate) { return $candidate }
    }
    return $null
}

function Find-ReadyVenv {
    $siblings = @(
        (Join-Path $RepoRoot ".venv\Scripts\python.exe"),
        (Join-Path (Split-Path -Parent $RepoRoot) "karaoke-party\.venv\Scripts\python.exe")
    )
    foreach ($exe in $siblings) {
        if (-not (Test-Path -LiteralPath $exe)) { continue }
        & $exe -c "import audio_separator, fastapi, uvicorn, numpy" 2>$null
        if ($LASTEXITCODE -eq 0) { return $exe }
    }
    return $null
}

function Install-Python {
    Write-Host "Python 3.11+ no esta instalado. Instalando Python 3.12 para este usuario..."
    $winget = Test-RealCommand "winget"
    if ($winget) {
        & winget install --id Python.Python.3.12 -e --scope user `
            --accept-package-agreements --accept-source-agreements --disable-interactivity
        $found = Find-Python
        if ($found) { return $found }
        Write-Host "winget no ha dejado Python a punto. Probando el instalador oficial..."
    }

    $listing = (& curl.exe -fsSL "https://www.python.org/ftp/python/") -join "`n"
    if ($LASTEXITCODE -ne 0) { throw "No se ha podido consultar python.org" }
    $versions = [regex]::Matches($listing, "3\.12\.\d+") | ForEach-Object { $_.Value } | Select-Object -Unique
    if (-not $versions) { throw "No se ha encontrado un instalador de Python 3.12" }
    $version = $versions | Sort-Object { [version]$_ } | Select-Object -Last 1
    $url = "https://www.python.org/ftp/python/$version/python-$version-amd64.exe"
    $installer = Join-Path $env:TEMP "python-$version-amd64.exe"
    Write-Host "Descargando $url"
    & curl.exe -fL --progress-bar -o $installer $url
    if ($LASTEXITCODE -ne 0) { throw "No se ha podido descargar Python" }
    Write-Host "Instalando Python $version..."
    $proc = Start-Process -FilePath $installer -ArgumentList @(
        "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_test=0",
        "Include_pip=1", "Include_launcher=1", "Shortcuts=0"
    ) -Wait -PassThru
    if ($proc.ExitCode -ne 0) { throw "El instalador de Python ha fallado (codigo $($proc.ExitCode))" }
    $found = Find-Python
    if (-not $found) { throw "Python se ha instalado pero no se encuentra python.exe" }
    return $found
}

function Ensure-Ffmpeg {
    $localBin = Join-Path $RepoRoot "tools\ffmpeg\bin"
    $localExe = Join-Path $localBin "ffmpeg.exe"
    if ((Test-Path -LiteralPath $localExe) -and (Test-Path -LiteralPath (Join-Path $localBin "ffprobe.exe"))) {
        return $localBin
    }
    $existing = Test-RealCommand "ffmpeg"
    $probe = Test-RealCommand "ffprobe"
    if ($existing -and $probe) { return $null }

    Write-Host "ffmpeg no esta instalado. Descargando una copia dentro de la carpeta del programa..."
    $tools = Join-Path $RepoRoot "tools"
    New-Item -ItemType Directory -Force -Path $tools | Out-Null
    $zip = Join-Path $tools "ffmpeg.zip"
    $urls = @(
        "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
    )
    $downloaded = $false
    foreach ($url in $urls) {
        Write-Host "Descargando $url"
        & curl.exe -fL --progress-bar -o $zip $url
        if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $zip)) {
            $downloaded = $true
            break
        }
    }
    if (-not $downloaded) { throw "No se ha podido descargar ffmpeg" }

    $extract = Join-Path $tools "ffmpeg-src"
    if (Test-Path -LiteralPath $extract) { Remove-Item -LiteralPath $extract -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $extract | Out-Null
    & tar.exe -xf $zip -C $extract
    if ($LASTEXITCODE -ne 0) { throw "No se ha podido descomprimir ffmpeg" }
    $ffmpeg = Get-ChildItem -LiteralPath $extract -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
    if (-not $ffmpeg) { throw "El archivo de ffmpeg no contiene ffmpeg.exe" }
    New-Item -ItemType Directory -Force -Path $localBin | Out-Null
    Copy-Item -Path (Join-Path $ffmpeg.DirectoryName "*") -Destination $localBin -Force
    Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $extract -Recurse -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path -LiteralPath (Join-Path $localBin "ffprobe.exe"))) {
        throw "La copia de ffmpeg no incluye ffprobe"
    }
    return $localBin
}

function Install-App([string]$BasePython) {
    $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Host "Creando el entorno de Stem Mixer..."
        & $BasePython -m venv (Join-Path $RepoRoot ".venv")
        if ($LASTEXITCODE -ne 0) { throw "No se ha podido crear el entorno virtual" }
    }
    & $venvPython -c "import audio_separator, fastapi, uvicorn, numpy" 2>$null
    if ($LASTEXITCODE -eq 0) { return $venvPython }

    Write-Host "Instalando Stem Mixer. La primera vez descarga PyTorch y puede tardar."
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "No se ha podido actualizar pip" }
    $nvidia = Test-RealCommand "nvidia-smi"
    if ($nvidia) {
        Write-Host "GPU NVIDIA detectada: instalando la version CUDA (unos 3 GB)."
        & $venvPython -m pip install -e ".[stems]"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "La instalacion GPU ha fallado. Probando la version CPU..."
            & $venvPython -m pip install -e ".[stems-cpu]"
        }
    } else {
        Write-Host "Sin GPU NVIDIA: instalando la version CPU. Separar una cancion sera mas lento."
        & $venvPython -m pip install -e ".[stems-cpu]"
    }
    if ($LASTEXITCODE -ne 0) { throw "No se han podido instalar las dependencias" }
    return $venvPython
}

if ($env:PROCESSOR_ARCHITECTURE -notin @("AMD64", "ARM64")) {
    throw "Hace falta Windows de 64 bits."
}

if ($DetectOnly) {
    $localBin = Join-Path $RepoRoot "tools\ffmpeg\bin\ffmpeg.exe"
    if (Test-Path -LiteralPath $localBin) {
        $ffmpegLabel = $localBin
    } elseif (Test-RealCommand "ffmpeg") {
        $ffmpegLabel = "PATH"
    } else {
        $ffmpegLabel = "(no instalado)"
    }
    $python = Find-Python
    $ready = Find-ReadyVenv
    Write-Host "ffmpeg: $ffmpegLabel"
    Write-Host ("python: " + $(if ($python) { $python } else { "(no instalado)" }))
    Write-Host ("entorno: " + $(if ($ready) { $ready } else { "(se creara en el primer arranque)" }))
    exit 0
}

$ffmpegBin = Ensure-Ffmpeg
if ($ffmpegBin) { $env:Path = "$ffmpegBin;$env:Path" }

$ready = Find-ReadyVenv
if (-not $ready) {
    $python = Find-Python
    if (-not $python) { $python = Install-Python }
    $ready = Install-App $python
}

$env:PYTHONPATH = Join-Path $RepoRoot "src"
Write-Host ""
Write-Host "Arrancando http://127.0.0.1:8780"
Write-Host "Cierra esta ventana para detener Stem Mixer."
Write-Host ""
& $ready -m stem_mixer --host 127.0.0.1 --port 8780
exit $LASTEXITCODE
