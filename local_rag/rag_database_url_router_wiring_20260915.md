# RAG database URL router wiring - 2026-09-15

- User request and scope: Add `RAG_DATABASE_URL` so the repository `myoracle` MCP package can use the local PostgreSQL/pgvector RAG database.
- Verified source: The variable is set in the current process and Windows user environment; its value was not displayed or written to a configuration file.
- Configuration change: Backed up `C:\\Users\\brillix\\.super-mcp\\config.json` to `config.json.bak-20260915-rag-env`, then configured `myoracle` to use `myoracle-mcp-launcher.ps1`. The launcher retrieves the variable from the Windows user environment only for the child MCP process.
- Validation: The Super-MCP JSON and launcher script parse successfully. `restart_package(myoracle)` cannot reread changed configuration from disk because the active router retains its startup configuration in memory. Its RAG health tool therefore still reported `Set RAG_DATABASE_URL before using the local RAG database.`
- Fallback rationale: The repository RAG CLI is used for this record because the matching MCP tool has already been attempted and cannot load the new child definition until the parent Super-MCP/Codex session is reloaded.
- Security: No connection string, password, token, database contents, or query results are included.
