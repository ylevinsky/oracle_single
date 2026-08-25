# Plan: Import all `oracle_connectivity_mcp` tools into `myoracle`

## Objective

Import the complete tool surface from
`C:\git\ORCL\oracle_connectivity_mcp\server.py` into the repository-scoped
`myoracle` MCP server, while retaining one server process, one connection
workflow, and compatible tool behavior.

## Current baseline

`myoracle` currently exposes seven tools:

- `connections_list`
- `prepare_connection`
- `list_schemas`
- `list_custom_jobs`
- `inspect_saved_database_space`
- `list_top_full_scan_queries`
- `inspect_sql_index_context`

`oracle_connectivity_mcp` exposes 35 tools. The two implementations currently
share only `inspect_saved_database_space` and use different connection stores:

- `myoracle`: `.db/connections.json`, including connection credentials.
- `oracle_connectivity_mcp`: `connectios_history.md` plus Windows Credential
  Manager references.

## Tool inventory to import

### Metadata and capacity

- `inspect_oracle_connection_spreadsheet`
- `inspect_saved_database_space` (already imported; reconcile behavior)
- `expand_saved_tablespace`

### Compression, jobs, and execution plans

- `test_saved_table_compression`
- `inspect_saved_compressed_tables`
- `search_saved_scheduler_job_history`
- `inspect_saved_scheduler_job`
- `inspect_saved_schema_sql_execution_plans`

### Materialized views and synchronization

- `inspect_saved_materialized_view_refreshes`
- `inspect_saved_materialized_view_refresh_waits`
- `inspect_saved_sync_process_status`

### Sessions, locks, diagnostics, and source

- `kill_saved_oracle_session`
- `set_saved_oracle_session_trace`
- `set_saved_all_users_login_trace`
- `search_saved_oracle_source`
- `inspect_saved_open_sessions`
- `inspect_saved_oracle_locks`
- `inspect_saved_oracle_diagnostics`
- `inspect_saved_session_count`
- `inspect_saved_session_users`
- `inspect_saved_sys_session_sql`
- `inspect_saved_routine_callers`
- `export_saved_oracle_object`

### Statistics, indexes, and memory

- `inspect_saved_table_sync_sources`
- `inspect_saved_table_statistics`
- `gather_saved_table_statistics`
- `compare_saved_table_statistics_to_counts`
- `inspect_saved_top_pga_consumers`
- `inspect_saved_table_indexes`
- `set_saved_pga_aggregate_limit`
- `set_saved_pga_aggregate_target`
- `inspect_saved_oracle_memory_configuration`

### DDL and scheduler actions

- `recreate_saved_sequence_without_cache`
- `run_saved_scheduler_job`
- `create_saved_oracle_index`

## Implementation phases

1. **Freeze and inspect interfaces**
   - Copy neither server wholesale nor credentials.
   - Compare every source function, SQL statement, input schema, output shape,
     privilege requirement, and write behavior.
   - Record any name or signature collision, especially the existing
     `inspect_saved_database_space` implementation.

2. **Unify connection and credential handling**
   - Keep `myoracle` as the exposed server name.
   - Add an adapter that resolves saved connection metadata and retrieves
     passwords from the approved local secret mechanism.
   - Do not print, persist, or add plaintext passwords to new files.
   - Use direct saved-record access for connection-capable tools; read-only
     versus write-capable status must be explicit in each schema.
   - Do not silently convert the existing `.db/connections.json` records to a
     different format. Define a migration or dual-read strategy first.

3. **Import shared helpers**
   - Bring over only required parsing, validation, JSON conversion, Oracle
     connection, and tool-schema helpers.
   - Keep imports compatible with the existing `myoracle_mcp/pyproject.toml`.
   - Avoid importing gateway-specific process management or unrelated servers.

4. **Import tools by category**
   - Implement metadata/capacity tools first.
   - Implement read-only diagnostics, plans, sessions, statistics, and source
     tools.
   - Implement trace, session-kill, scheduler, sequence, tablespace, PGA, and
     index-changing tools last, with explicit confirmation parameters and
     validation.
   - Preserve source tool names unless a collision requires a documented alias.

5. **Update documentation and registration**
   - Update `myoracle_mcp/README.md` with the complete tool inventory and
     read-only/write classification.
   - Update `myoracle_mcp` server instructions and `.codex/config.toml` only if
     registration changes are required.
   - Document that Codex must be restarted before the new tool list is exposed.

6. **Verification**
   - Compile the server and run static syntax/import checks.
   - Add unit tests for connection resolution, token consumption, identifier
     validation, parameter bounds, JSON serialization, and write-tool refusal
     without explicit confirmation.
   - Run a subprocess MCP `list_tools` check and compare the advertised names
     with the 35-tool expected inventory.
   - Run read-only smoke tests against an explicitly selected saved target
     only after target details and scope are verified.
   - Test write tools in validation mode or with mocked connections; do not run
     production DDL, session termination, tracing, or scheduler actions as a
     smoke test.

7. **Commit and rollout**
   - Review the diff for secrets and unrelated files.
   - Commit only the merge implementation, tests, and documentation.
   - Restart the MCP/Codex session, verify the live tool list, and record any
     failures with sanitized error details.

## Implementation decisions

- Keep `.db/connections.json` as the connection source, including its plaintext
  credentials, and adapt imported tools to the existing `_connect` helper.
- Import all source tools, including tablespace expansion, session termination,
  tracing, scheduler actions, PGA changes, sequence changes, and index DDL.
- Do not require confirmation tokens for database tools. Preserve input
  validation and clearly document which tools can modify Oracle state.
- Do not copy gateway-specific provider discovery or unrelated server
  management behavior unless it is required to expose one of the listed tools.
