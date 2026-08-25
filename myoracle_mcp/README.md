# myoracle MCP server

Repository-scoped MCP server for Oracle connections stored in
`.db/connections.json`.

The server exposes seven tools:

- `connections_list`: lists saved Oracle connection names without connecting.
- `prepare_connection`: reads and returns every saved connection detail.
- `list_schemas`: connects once and queries `DBA_USERS`.
- `list_custom_jobs`: connects once and lists Scheduler
  and legacy jobs owned by users where `ORACLE_MAINTAINED = 'N'`.
- `inspect_saved_database_space`: connects once and
  reports allocated, free, and AUTOEXTEND capacity for online permanent and
  UNDO tablespaces.
- `list_top_full_scan_queries`: ranks shared-pool SQL from non-Oracle-maintained
  parsing schemas whose plans contain `TABLE ACCESS FULL`.
- `inspect_sql_index_context`: returns active plan predicates, object statistics,
  relevant column statistics, and existing indexes for a SQL ID.

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
