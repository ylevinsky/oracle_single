# myoracle MCP server

Repository-scoped MCP server for Oracle connections stored in
`.db/connections.json`.

The server exposes seven tools:

- `connections_list`: lists saved Oracle connection names without connecting.
- `prepare_connection`: reads and returns every saved detail, including the
  password, plus a short-lived one-time confirmation token.
- `list_schemas`: consumes that token, connects once, and queries `DBA_USERS`.
- `list_custom_jobs`: consumes that token, connects once, and lists Scheduler
  and legacy jobs owned by users where `ORACLE_MAINTAINED = 'N'`.
- `inspect_saved_database_space`: consumes that token, connects once, and
  reports allocated, free, and AUTOEXTEND capacity for online permanent and
  UNDO tablespaces.
- `list_top_full_scan_queries`: ranks shared-pool SQL from non-Oracle-maintained
  parsing schemas whose plans contain `TABLE ACCESS FULL`.
- `inspect_sql_index_context`: returns active plan predicates, object statistics,
  relevant column statistics, and existing indexes for a SQL ID.

The two-step flow enforces the repository rule that connection details must be
shown and reconfirmed before every database connection attempt. A token expires
after ten minutes, cannot be reused, and becomes invalid if the saved record is
edited.

## Setup and verification

From the repository root:

```powershell
uv sync --project .\myoracle_mcp
uv run --project .\myoracle_mcp python -m compileall .\myoracle_mcp\server.py
```

Codex registration is in the repository's `.codex/config.toml`. Restart Codex
or open a new task in this trusted repository after installation so it discovers
the `myoracle` tools.
