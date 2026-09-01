# myoracle MCP server

Repository-scoped MCP server for Oracle connections stored in
`.db/connections.json`.

The server exposes 43 tools: the nine repository-scoped tools listed below,
plus the 34 additional tools imported from the maintained Oracle implementation
in `C:\git\ORCL\oracle_connectivity_mcp\server.py`.

- `connections_list`: lists saved Oracle connection names without connecting.
- `prepare_connection`: reads and returns every saved connection detail.
- `list_schemas`: connects once and queries `DBA_USERS`.
- `list_custom_jobs`: connects once and lists Scheduler
  and legacy jobs owned by users where `ORACLE_MAINTAINED = 'N'`.
- `inspect_saved_database_space`: connects once and
  reports allocated, free, and AUTOEXTEND capacity for online permanent and
  UNDO tablespaces.
- `inspect_all_saved_database_space`: checks every saved Oracle target and
  returns per-target capacity results or sanitized connection errors.
- `inspect_local_rag_database`: checks the local RAG PostgreSQL database,
  pgvector extension, and required RAG tables.
- `list_top_full_scan_queries`: ranks shared-pool SQL from non-Oracle-maintained
  parsing schemas whose plans contain `TABLE ACCESS FULL`.
- `inspect_sql_index_context`: returns active plan predicates, object statistics,
  relevant column statistics, and existing indexes for a SQL ID.

The imported tools cover connection metadata, tablespace capacity and expansion,
compression, Scheduler jobs, execution plans, materialized views, sync status,
sessions, locks, diagnostics, source and object export, statistics, indexes,
memory, tracing, sequence recreation, Scheduler execution, and index creation.
Their original names and signatures are preserved. They run in this single
`myoracle` MCP process and use `.db/connections.json` through the repository
connection adapter.

Database tools use the saved connection record directly. Write-capable tools
must still validate their arguments and clearly identify their state-changing
operation.

## Setup and verification

From the repository root:

```powershell
uv sync --project .\myoracle_mcp
uv run --project .\myoracle_mcp python -m compileall .\myoracle_mcp\server.py
```

Codex registration is in the repository's `.codex/config.toml`. Restart Codex
or open a new task in this trusted repository after installation so it discovers
the `myoracle` tools.
