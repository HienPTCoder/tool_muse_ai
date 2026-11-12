#!/bin/bash
# Nhấp đúp để mở Muse Video Studio
cd "$(dirname "$0")"
studio_root="$(pwd)"
# Dừng bản Muse Video Studio cũ của chính thư mục này nếu vẫn đang chiếm cổng mặc định.
if command -v lsof >/dev/null; then
  for studio_pid in $(lsof -tiTCP:8765 -sTCP:LISTEN 2>/dev/null); do
    studio_dir="$(lsof -a -p "$studio_pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')"
    if [ "$studio_dir" = "$studio_root" ]; then
      kill "$studio_pid" 2>/dev/null || true
    fi
  done
  for studio_attempt in $(seq 1 30); do
    studio_busy=0
    for studio_pid in $(lsof -tiTCP:8765 -sTCP:LISTEN 2>/dev/null); do
      studio_dir="$(lsof -a -p "$studio_pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')"
      if [ "$studio_dir" = "$studio_root" ]; then studio_busy=1; fi
    done
    [ "$studio_busy" -eq 0 ] && break
    sleep 0.2
  done
fi
if [ ! -d .venv ]; then
  echo "Cài đặt lần đầu…"
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
fi
command -v ffmpeg >/dev/null || { echo "Thiếu ffmpeg: chạy 'brew install ffmpeg'"; exit 1; }
exec .venv/bin/python app.py
