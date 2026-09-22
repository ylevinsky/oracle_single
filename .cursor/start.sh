#!/usr/bin/env bash
# Per-boot service reconciliation. Starts PostgreSQL and Ollama, waits for
# readiness, then returns. Safe to run repeatedly.
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"

echo "==> Starting PostgreSQL"
sudo pg_ctlcluster 16 main start 2>/dev/null || true
for _ in $(seq 1 30); do
  if sudo -u postgres pg_isready -q; then break; fi
  sleep 1
done
sudo -u postgres pg_isready || { echo "PostgreSQL failed to become ready" >&2; exit 1; }

echo "==> Starting Ollama"
if ! pgrep -x ollama >/dev/null 2>&1; then
  nohup ollama serve >/tmp/ollama.log 2>&1 &
fi
for _ in $(seq 1 30); do
  if curl -sf http://127.0.0.1:11434/api/version >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -sf http://127.0.0.1:11434/api/version >/dev/null || { echo "Ollama failed to become ready" >&2; exit 1; }

echo "Services ready: PostgreSQL + Ollama"
