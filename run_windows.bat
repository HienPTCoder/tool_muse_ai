@echo off
setlocal
chcp 65001 >nul
title Muse Video Studio
cd /d "%~dp0"

rem --- Kiem tra ffmpeg / ffprobe ---
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [LOI] Thieu FFmpeg. Cai FFmpeg va them ffmpeg.exe, ffprobe.exe vao PATH.
  echo       Goi y: winget install Gyan.FFmpeg
  pause
  exit /b 1
)
where ffprobe >nul 2>nul
if errorlevel 1 (
  echo [LOI] Thieu FFprobe. Them ffprobe.exe vao PATH.
  pause
  exit /b 1
)

rem --- Tim Python ---
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo [LOI] Chua cai Python 3.11 tro len. Cai tu https://www.python.org va tick "Add to PATH".
  pause
  exit /b 1
)

rem --- Dung ban cu dang chiem cong 8765 ---
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8765 .*LISTENING"') do (
  echo Dung tien trinh cu tren cong 8765 (PID %%P)...
  taskkill /PID %%P /F >nul 2>nul
)

rem --- Cai dat lan dau ---
if not exist ".venv\Scripts\python.exe" (
  echo Cai dat lan dau, vui long cho...
  %PY% -m venv .venv
  if errorlevel 1 goto :failed
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  if errorlevel 1 goto :failed
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :failed
)

echo Dang mo Muse Video Studio tai http://127.0.0.1:8765
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto :failed
exit /b 0

:failed
echo.
echo [LOI] Muse Video Studio khong khoi dong duoc. Xem thong bao phia tren.
pause
exit /b 1
