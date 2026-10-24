#!/usr/bin/env bash
# Backend 自愈守护：uvicorn 崩溃/退出后 2 秒自动重启，避免"数据源断"靠人工拉起。
# 用法：bash supervise_backend.sh   （由 PowerShell Start-Process 完全脱离会话启动）
set -u
cd "$(dirname "$0")"

PORT=18080
PY="./.venv/Scripts/python.exe"
LOG="supervise.log"

echo "[supervise] pid=$$ started at $(date)" >> "$LOG"
while true; do
  echo "[supervise] -> starting uvicorn :$PORT at $(date)" >> "$LOG"
  "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" >> "$LOG" 2>&1
  code=$?
  echo "[supervise] uvicorn exited code=$code at $(date); restart in 2s" >> "$LOG"
  sleep 2
done
