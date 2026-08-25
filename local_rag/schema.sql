CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rag_documents (
    id bigserial PRIMARY KEY,
    source_path text NOT NULL UNIQUE,
    content_sha256 text NOT NULL,
    indexed_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rag_chunks (
    id bigserial PRIMARY KEY,
    document_id bigint NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
    chunk_index integer NOT NULL,
    content text NOT NULL,
    embedding vector(1024) NOT NULL,
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS rag_chunks_embedding_hnsw
    ON rag_chunks USING hnsw (embedding vector_cosine_ops);
