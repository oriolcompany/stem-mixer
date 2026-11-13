@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Stem Mixer

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap.ps1" -RepoRoot "%~dp0."
if errorlevel 1 (
  echo.
  echo No se ha podido arrancar Stem Mixer.
  pause
)
endlocal
