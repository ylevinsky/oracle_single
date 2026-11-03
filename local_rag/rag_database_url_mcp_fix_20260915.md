# RAG_DATABASE_URL MCP fix - 2026-09-15

- Request and scope: restore local PostgreSQL RAG access through the Super-MCP routed `myoracle` package without storing or exposing the RAG connection string.
- Cause: the live Super-MCP package was started with a direct Python command and did not inherit `RAG_DATABASE_URL`. Restarting the package retained that cached command.
- Configuration: backed up `C:\Users\brillix\.super-mcp\config.json` as `config.json.bak-20260915-2007` and changed only `myoracle` to use the existing hidden PowerShell launcher. The launcher reads the Windows user environment and passes the value only to its child process; the URL was not written to configuration.
- Code fix: `myoracle_mcp/server.py` now falls back to the Windows user environment only when the process environment lacks `RAG_DATABASE_URL`. The fallback returns no value on non-Windows systems and does not log or persist the value. Regression coverage was added in `myoracle_mcp/test_server.py`.
- Verification: compilation and six unit tests passed. After `myoracle` package restart, `inspect_local_rag_database` returned `healthy: true`, database `rag`, pgvector installed, and both `rag_documents` and `rag_chunks` tables present.
- Handled errors: PowerShell `Copy-Item` rejected unsupported `-NoClobber`; the backup was then created after an explicit existence check. The first text patch used mismatched whitespace and was rejected without modifying the configuration; the corrected patch applied successfully.
- Indexing status: the routed RAG-ingestion request did not return and was terminated after approximately two minutes. This sanitized record is retained locally; its indexed status is unverified.
