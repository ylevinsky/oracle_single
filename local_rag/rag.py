"""Small local RAG CLI using Ollama embeddings and PostgreSQL/pgvector."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import psycopg


ROOT = Path(__file__).resolve().parent
MODEL = os.environ.get("RAG_EMBEDDING_MODEL", "mxbai-embed-large")
OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
DATABASE_URL = os.environ.get("RAG_DATABASE_URL")
CHUNK_SIZE = 1_200
CHUNK_OVERLAP = 200
TEXT_EXTENSIONS = {".md", ".txt", ".csv", ".json", ".py", ".sql", ".yaml", ".yml"}


def database_url() -> str:
    if not DATABASE_URL:
        raise RuntimeError("Set RAG_DATABASE_URL before using the RAG database.")
    return DATABASE_URL


def embed(texts: list[str]) -> list[list[float]]:
    """Embed input with Ollama, loading the model on demand and keeping it warm."""
    payload = json.dumps(
        {"model": MODEL, "input": texts, "keep_alive": "10m"}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{OLLAMA_URL}/api/embed",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.load(response)
    except urllib.error.URLError as exc:
        raise RuntimeError(
            "Ollama is unavailable. Start it, then run: ollama pull mxbai-embed-large"
        ) from exc
    vectors = result.get("embeddings")
    if not isinstance(vectors, list) or len(vectors) != len(texts):
        raise RuntimeError(f"Unexpected Ollama embedding response: {result!r}")
    if any(len(vector) != 1024 for vector in vectors):
        raise RuntimeError(
            f"{MODEL} returned unexpected dimensions; this RAG schema requires 1024."
        )
    return vectors


def chunks(text: str) -> list[str]:
    text = text.strip()
    return [text[start : start + CHUNK_SIZE] for start in range(0, len(text), CHUNK_SIZE - CHUNK_OVERLAP)]


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(map(str, vector)) + "]"


def init_database(_: argparse.Namespace) -> None:
    with psycopg.connect(database_url()) as connection:
        connection.execute((ROOT / "schema.sql").read_text(encoding="utf-8"))
    print("RAG schema initialized.")


def source_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return [file for file in path.rglob("*") if file.suffix.lower() in TEXT_EXTENSIONS]


def ingest(args: argparse.Namespace) -> None:
    files = source_files(Path(args.path).resolve())
    if not files:
        raise RuntimeError("No supported text files found.")
    with psycopg.connect(database_url()) as connection:
        for file in files:
            content = file.read_text(encoding="utf-8", errors="replace")
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            existing = connection.execute(
                "SELECT id, content_sha256 FROM rag_documents WHERE source_path = %s", (str(file),)
            ).fetchone()
            if existing and existing[1] == digest:
                print(f"Unchanged: {file}")
                continue
            if existing:
                document_id = existing[0]
                connection.execute("DELETE FROM rag_chunks WHERE document_id = %s", (document_id,))
                connection.execute(
                    "UPDATE rag_documents SET content_sha256 = %s, indexed_at = now() WHERE id = %s",
                    (digest, document_id),
                )
            else:
                document_id = connection.execute(
                    "INSERT INTO rag_documents (source_path, content_sha256) VALUES (%s, %s) RETURNING id",
                    (str(file), digest),
                ).fetchone()[0]
            pieces = chunks(content)
            for index, (piece, vector) in enumerate(zip(pieces, embed(pieces))):
                connection.execute(
                    "INSERT INTO rag_chunks (document_id, chunk_index, content, embedding) VALUES (%s, %s, %s, %s::vector)",
                    (document_id, index, piece, vector_literal(vector)),
                )
            print(f"Indexed {len(pieces)} chunks: {file}")


def query(args: argparse.Namespace) -> None:
    question_vector = vector_literal(embed([args.question])[0])
    with psycopg.connect(database_url()) as connection:
        rows = connection.execute(
            """SELECT d.source_path, c.chunk_index, c.content, 1 - (c.embedding <=> %s::vector) AS similarity
                 FROM rag_chunks c JOIN rag_documents d ON d.id = c.document_id
                 ORDER BY c.embedding <=> %s::vector LIMIT %s""",
            (question_vector, question_vector, args.limit),
        ).fetchall()
    for source_path, chunk_index, content, similarity in rows:
        print(f"\n[{similarity:.3f}] {source_path} (chunk {chunk_index})\n{content}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Local PostgreSQL/pgvector RAG")
    commands = parser.add_subparsers(required=True)
    init = commands.add_parser("init", help="create the RAG tables and vector index")
    init.set_defaults(action=init_database)
    ingest_parser = commands.add_parser("ingest", help="index a text file or directory")
    ingest_parser.add_argument("path")
    ingest_parser.set_defaults(action=ingest)
    query_parser = commands.add_parser("query", help="retrieve relevant local chunks")
    query_parser.add_argument("question")
    query_parser.add_argument("--limit", type=int, default=5)
    query_parser.set_defaults(action=query)
    args = parser.parse_args()
    try:
        args.action(args)
    except RuntimeError as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
