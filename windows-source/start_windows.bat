@echo off
setlocal
cd /d "%~dp0"

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo FFmpeg was not found. Install FFmpeg and add ffmpeg.exe and ffprobe.exe to PATH.
  pause
  exit /b 1
)
where ffprobe >nul 2>nul
if errorlevel 1 (
  echo FFprobe was not found. Install FFmpeg and add ffprobe.exe to PATH.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 -m venv .venv
  ) else (
    python -m venv .venv
  )
  if errorlevel 1 goto :failed
  .venv\Scripts\python.exe -m pip install --upgrade pip
  if errorlevel 1 goto :failed
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 goto :failed
)

.venv\Scripts\python.exe app.py
if errorlevel 1 goto :failed
exit /b 0

:failed
echo Muse Video Studio could not start. Check the messages above.
pause
exit /b 1
