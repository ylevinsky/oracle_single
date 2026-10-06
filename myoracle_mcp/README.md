# myoracle MCP server

Repository-scoped MCP server for Oracle connections stored in
`.db/connections.json`.

The server exposes 50 tools: the repository-scoped tools listed below,
plus the 34 additional tools imported from the maintained Oracle implementation
in `C:\git\ORCL\oracle_connectivity_mcp\server.py`.

- `connections_list`: lists saved Oracle connection names without connecting.
- `migrate_mobaxterm_to_mremoteng`: imports SSH/RDP bookmarks from MobaXterm
  into a complete mRemoteNG connection file, creates a timestamped backup,
  and leaves connection passwords blank so startup does not prompt.
  `remove_names` drops placeholder nodes (e.g. a `test` marker) before importing.
- `set_mremoteng_file_password`: sets a custom password on an mRemoteNG
  connection file so startup asks for that password.
- `restore_mobaxterm_passwords`: copies saved MobaXterm account passwords
  into an existing mRemoteNG file. The result reports which connections
  received a password and never returns the password text.
- `prepare_connection`: reads and returns every saved connection detail.
- `list_schemas`: connects once and queries `DBA_USERS`.
- `compare_saved_application_objects`: read-only comparison of user tables
  and application procedures, functions, and packages. Row counts come from
  optimizer statistics. Structure and PL/SQL source are compared by signature.
- `list_saved_user_tables`: lists non-Oracle-maintained schemas and the
  tables in each schema, including schemas that contain no tables.
- `compare_saved_schema_movement`: read-only comparison of non-Oracle-maintained
  schemas between two saved connections, including segment size, optimizer
  table statistics, database links, materialized views, Scheduler jobs, and
  Data Pump jobs that can move data from the source to the target.
- `list_custom_jobs`: connects once and lists Scheduler
  and legacy jobs owned by users where `ORACLE_MAINTAINED = 'N'`.
- `inspect_saved_database_space`: connects once and
  reports allocated, free, and AUTOEXTEND capacity for online permanent and
  UNDO tablespaces.
- `collect_saved_backup_scripts`: copies backup, dependency, and restore script
  files from an SSH-accessible saved host into `rman/scripts/<site>`.
- `inspect_saved_alert_log_errors`: checks recent Oracle alert-log records and
  reports matching errors.
- `summarize_saved_alert_log_codes`: counts `ORA-`, `TNS-`, and `RMAN-` codes
  in the last 5000 alert-log lines.
- `check_saved_oracle_connectivity`: opens and closes one saved Oracle connection.
- `get_local_current_date`: returns today's local date in ISO 8601 format.
- `inspect_saved_backup_log_errors`: scans recent remote backup logs and
  reports matching errors.
- `run_saved_targets_routine`: sequentially checks reachable targets for free
  space, alert-log errors, backup-log errors, and copies backup job scripts.
- `inspect_all_saved_database_space`: checks every saved Oracle target and
  returns per-target capacity results or sanitized connection errors.
- `daily_rutione_check`: on demand, checks tablespace capacity, alert-log
  errors from the last 5000 lines, and RMAN backup
  health. It reports only tablespaces below the requested free-space threshold,
  ORA/TNS/RMAN codes found in that alert-log tail,
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
  A saved Oracle target that cannot be reached is reported as not connected.
  The complete result is also written to `report.md` at the repository root.
  Supply `slack_channel_id` to override that destination.
  The `MCP/Slack` Credential Manager token is used for delivery.
- `configure_daily_routine_schedule`: creates or updates the local Windows Task
  Scheduler task `\\OracleMCP\\DailyRoutine` for daily execution at 08:00. Its
  runner calls `daily_rutione_check`, prints the full result locally, and sends the configured default Slack DM.
- `resolve_slack_channel`: resolves a visible Slack channel name (such as
  `essence`) to the ID required by `daily_rutione_check` notifications.
- `list_top_sql_memory`: ranks non-Oracle-maintained SQL by shared-pool memory
  (`SHARABLE_MEM + PERSISTENT_MEM + RUNTIME_MEM`).
- `list_local_postgres_databases`: lists every database on one saved
  PostgreSQL connection (default `local_postgres_admin`), including owner,
  encoding, size, and whether connections are allowed.
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
- `create_saved_transfer_products_queue`: creates `ATE_RESULTS.TRANSFER_PRODUCTS_QUEUE`
  on a saved site, copies current `TRANSFER_PRODUCTS_LOG` rows into it once, and
  updates the insert trigger to write the log and the queue. The log stays
  insert-only. It requires `confirmed=true`.
- `create_philippines_refresh_objects`: creates the missing Repair Center
  Philippines refresh tables, serial index, and materialized views. Existing
  objects are left unchanged. It requires `confirmed=true` and does not refresh
  or copy rows.
- `inspect_saved_object_privileges`: lists direct object grants for one grantee
  on a saved Oracle connection. An optional object name narrows the list.
- `check_saved_database_link`: reads one row through a named database link on
  a saved Oracle connection and reports whether the link responded. A private
  link owned by another user is probed as that owner.
- `recreate_public_database_link_from_existing`: drops one public database
  link and copies an existing link into its place. The password verifier stays
  in the database. It requires `confirmed=true`.
- `create_public_database_link_from_existing`: creates a public database link
  by copying an existing link on that database. The password verifier stays in
  the database. It requires `confirmed=true`.
- `reset_ate_results_password_and_recreate_ph_links`: sets the Philippines
  `ATE_RESULTS` password and recreates the public and private `PH_DB` links.
  The password is not returned. It requires `confirmed=true`.
- `create_philippines_public_database_link`: creates public link `PH_DB` from
  Spain Repair Center to the Philippines database. It creates remote user
  `PH_DBLINK` for that link and does not return the password. It requires
  `confirmed=true`.
- `create_saved_readonly_user`: creates (or resets) a read-only user on a
  saved Oracle connection. It grants `CREATE SESSION` plus `SELECT ANY TABLE`
  (and `SELECT ANY DICTIONARY` when `with_dictionary_access=true`), unlocks
  the account, and never returns the password. It requires `confirmed=true`.
- `check_ephemeral_oracle_connectivity`: opens and closes one Oracle
  connection reusing every saved detail from `base_connection_name` (user,
  privilege mode, service/SID, credentials) with only `host` (and optionally
  `port`) overridden. Nothing is persisted to `.db/connections.json`.
- `check_saved_last_scn_date`: returns the current SCN from `V$DATABASE` and
  the timestamp `SCN_TO_TIMESTAMP` maps it to, next to the database `SYSDATE`.
  Uses the saved host unless `host` (and optionally `port`) is overridden;
  overridden checks reuse the saved credentials and persist nothing.
- `check_saved_clone_and_start_time`: returns the clone snapshot time and the
  instance start time for a saved Oracle connection. While the frozen
  `checkpoint_time` from `v$datafile_header` still predates this instance's
  startup, that checkpoint is reported as the snapshot time. Once this
  instance has overwritten the headers with its own checkpoints, the snapshot
  window is derived from this clone's own `v$archived_log` instead (last log
  fully archived before startup through this instance's startup, plus the
  last source SCN archived). Also reports checkpoint consistency across
  datafiles, the frozen SCN range, and the database time. Uses the saved host
  unless `host` (and optionally `port`) is overridden; overridden checks reuse
  the saved credentials and persist nothing.
- `run_saved_oracle_query`: runs one read-only `SELECT`/`WITH` statement on a
  saved Oracle connection and returns columns plus up to `max_rows` rows
  (1-5000, default 500). Statements containing DML, DDL, `FOR UPDATE`,
  PL/SQL calls, or extra statements are rejected before connecting. Uses the
  saved host unless `host` (and optionally `port`) is overridden. Pass
  `service_name` to override the saved service (empty string connects by
  SID), or `sid` to override the saved SID; overridden runs persist nothing.
- `list_saved_table_timestamp_ranges`: for every table owned by a
  non-Oracle-maintained schema that has DATE or TIMESTAMP columns, reports
  the owner, table name, those columns, segment size in MB, and the overall
  latest and earliest timestamp value, ordered by segment size, largest
  first. One aggregate query runs per table with a two-minute call timeout;
  failures are reported per table. Tables whose name contains `$` are never
  queried and never reported — this covers materialized view logs
  (`MLOG$_...`, `RUPD$_...`) and other internal-style names; the excluded
  count is returned as `tables_excluded_dollar_or_mv_log`. Optional
  `max_tables` limits the output. Uses the saved host unless `host` (and
  optionally `port`) is overridden; overridden runs persist nothing.

The imported tools cover connection metadata, tablespace capacity and expansion,
compression, Scheduler jobs, execution plans, materialized views, sync status,
sessions, locks, diagnostics, source and object export, object retirement
(materialized view drop), statistics, indexes,
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
