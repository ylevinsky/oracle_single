SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = 'rag'
  AND pid <> pg_backend_pid();

DROP DATABASE IF EXISTS rag;
CREATE DATABASE rag;

\connect rag
CREATE EXTENSION IF NOT EXISTS vector;

SELECT current_database() AS database,
       extname AS extension,
       extversion AS version
FROM pg_extension
WHERE extname = 'vector';
