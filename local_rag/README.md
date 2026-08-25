# Local RAG

This RAG uses `mxbai-embed-large` through local Ollama and PostgreSQL with
pgvector. Every `ingest` and `query` call asks Ollama for embeddings; Ollama
loads the model automatically if it is inactive and keeps it loaded for ten
minutes.

## One-time setup

```powershell
ollama pull mxbai-embed-large
uv sync --project .\local_rag
$env:RAG_DATABASE_URL = "postgresql://USER:PASSWORD@HOST:PORT/rag"
uv run --project .\local_rag python .\local_rag\rag.py init
```

`init` changes the database. Confirm the connection details required by this
repository before running it.

## Index and search

```powershell
uv run --project .\local_rag python .\local_rag\rag.py ingest .\dwh
uv run --project .\local_rag python .\local_rag\rag.py query "your question"
```

Supported sources are Markdown, text, CSV, JSON, Python, SQL, YAML, and YML.
Changing embedding models requires recreating/reindexing the RAG data because
the vectors are model-specific.
