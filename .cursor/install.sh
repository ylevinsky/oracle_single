#!/usr/bin/env bash
# Idempotent repository bootstrap for the Cloud Agent environment.
# System packages (PostgreSQL 16 + pgvector, Ollama, uv, zstd) are baked into
# the base snapshot; this script prepares repository-derived state after the
# source tree is checked out.
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

RAG_DATABASE_URL="${RAG_DATABASE_URL:-postgresql://rag:rag@127.0.0.1:5432/rag}"

echo "==> Installing Python dependencies with uv"
uv sync --project ./myoracle_mcp
uv sync --project ./local_rag

echo "==> Ensuring PostgreSQL is running"
sudo pg_ctlcluster 16 main start 2>/dev/null || true
for _ in $(seq 1 30); do
  if sudo -u postgres pg_isready -q; then break; fi
  sleep 1
done

echo "==> Ensuring RAG role, database, and pgvector extension exist"
sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='rag'" | grep -q 1 \
  || sudo -u postgres psql -c "CREATE ROLE rag LOGIN PASSWORD 'rag';"
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='rag'" | grep -q 1 \
  || sudo -u postgres createdb -O rag rag
sudo -u postgres psql -d rag -c "CREATE EXTENSION IF NOT EXISTS vector; GRANT ALL ON SCHEMA public TO rag;"

echo "==> Ensuring Ollama is running and the embedding model is present"
if ! pgrep -x ollama >/dev/null 2>&1; then
  nohup ollama serve >/tmp/ollama.log 2>&1 &
fi
for _ in $(seq 1 30); do
  if curl -sf http://127.0.0.1:11434/api/version >/dev/null 2>&1; then break; fi
  sleep 1
done
if ! ollama list 2>/dev/null | grep -q "mxbai-embed-large"; then
  ollama pull mxbai-embed-large
fi

echo "==> Initializing the local RAG schema (idempotent)"
RAG_DATABASE_URL="$RAG_DATABASE_URL" uv run --project ./local_rag python ./local_rag/rag.py init

echo "Install complete."
