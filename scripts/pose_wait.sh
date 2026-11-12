#!/bin/bash
# Chờ đến khi các dự án trong kế hoạch hết việc đang chạy/xếp hàng, rồi in tình trạng. Dùng: pose_wait.sh plan.json
cd "$(dirname "$0")/.."
while .venv/bin/python scripts/pose_batch.py status "$1" | grep -q "đang chạy"; do sleep 30; done
.venv/bin/python scripts/pose_batch.py status "$1"
