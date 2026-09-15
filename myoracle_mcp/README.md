# myoracle MCP server

Repository-scoped MCP server for Oracle connections stored in
`.db/connections.json`.

The server exposes 45 tools: the nine repository-scoped tools listed below,
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
- `collect_saved_backup_scripts`: copies backup, dependency, and restore script
  files from an SSH-accessible saved host into `rman/scripts/<site>`.
- `inspect_saved_alert_log_errors`: checks recent Oracle alert-log records and
  reports matching errors.
- `inspect_saved_backup_log_errors`: scans recent remote backup logs and
  reports matching errors.
- `run_saved_targets_routine`: sequentially checks reachable targets for free
  space, alert-log errors, backup-log errors, and copies backup job scripts.
- `inspect_all_saved_database_space`: checks every saved Oracle target and
  returns per-target capacity results or sanitized connection errors.
- `daily_rutione_check`: on demand, checks tablespace capacity and RMAN backup
  health. It reports only tablespaces below the requested free-space threshold,
  failed RMAN jobs in the last 14 days, a missing level-1 incremental in three
  days, or a missing level-0 full backup in 14 days. The backup-level checks join
  RMAN job details to `V$BACKUP_SET_DETAILS` by session key. It sends a detailed
  aggregate notification to the `daily_routine.slack_user_id` configured in `config.yaml`.
  The file uses JSON-compatible YAML and stores a Slack user ID, so the bot opens
  its own DM channel. The complete report is split into readable parts (up to
  three messages).
  For Spain (`es_db2_orclsp_sys`) it also includes up to five `refresh_mv.py`
  `DAILY_TRANSFER` errors from the last 48 hours, or a failure status when no
  execution is recorded in that period. Generic job and refresh statuses remain
  outside the report.
  Supply `slack_channel_id` to override that destination.
  The `MCP/Slack` Credential Manager token is used for delivery.
- `configure_daily_routine_schedule`: creates or updates the local Windows Task
  Scheduler task `\\OracleMCP\\DailyRoutine` for daily execution at 08:00. Its
  runner calls `daily_rutione_check`, including the configured default Slack DM.
- `resolve_slack_channel`: resolves a visible Slack channel name (such as
  `essence`) to the ID required by `daily_rutione_check` notifications.
- `list_top_sql_memory`: ranks non-Oracle-maintained SQL by shared-pool memory
  (`SHARABLE_MEM + PERSISTENT_MEM + RUNTIME_MEM`).
- `inspect_local_rag_database`: checks the local RAG PostgreSQL database,
  pgvector extension, and required RAG tables.
- `ingest_local_rag_markdown`: ingests a Markdown file or directory into the
  local PostgreSQL RAG database.
- `list_top_full_scan_queries`: ranks shared-pool SQL from non-Oracle-maintained
  parsing schemas whose plans contain `TABLE ACCESS FULL`.
- `inspect_sql_index_context`: returns active plan predicates, object statistics,
  relevant column statistics, and existing indexes for a SQL ID.
- `search_saved_oracle_source`: searches stored procedure, function, package,
  package-body, and trigger source for one to three terms.
- `inspect_saved_table_sync_sources`: identifies stored-code references,
  triggers, dependencies, and related jobs for a table.

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
