# Local RAG PostgreSQL health check - 2026-09-15

- Request and scope: determine whether the local PostgreSQL RAG database on `localhost:5432`, database `rag`, is running.
- Verified service state: Windows service `postgresql-x64-18` was `Running` with start type `Automatic`.
- Verified listener state: `pg_isready -h localhost -p 5432 -d rag` returned `localhost:5432 - accepting connections`.
- Configuration state: `RAG_DATABASE_URL` is set in the interactive shell, but the Super-MCP `myoracle__inspect_local_rag_database` tool was unable to access it.
- Handled error: the MCP diagnostic returned `Set RAG_DATABASE_URL before using the local RAG database.` This is an MCP process-environment configuration issue, not evidence that PostgreSQL is down. No code or service change was made.
- Indexing status: this record could not be ingested through the same MCP runtime because its database URL is unavailable; indexing is unverified until that configuration is corrected.
