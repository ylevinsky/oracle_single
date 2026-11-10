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
- `upload_files_to_saved_host`: copies selected files from `ORCL/` to a saved
  SSH host with Windows `scp`. The password is passed through an askpass
  program and is not placed on the command line.
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
  three messages). When the findings outgrow three messages, the notifier
  switches to a compact one-line-per-target rendering so every problem is still
  delivered instead of dropping the notification.
  For Spain (`es_db2_orclsp_sys`) it also includes up to five `refresh_mv.py`
  `DAILY_TRANSFER` errors from the last 48 hours, a `refresh_mv_backlog_breach`
  alert for any site whose eligible staging backlog reaches 100 rows or whose
  oldest eligible `LAST_TEST_DATE` is at least 24 hours old, using Oracle's
  `SYSDATE` for the age comparison. Eligible means the serial and RF are absent
  from `GLOBAL_UUT_ATTRIBUTES`; null RF values are eligible when the serial is
  absent, matching the sync copy predicate. The counts describe staging rows,
  including any duplicate keys within a batch. Failed backlog queries produce
  `refresh_mv_backlog_check_failed` alerts and null counts, not healthy zeros.
  Backlog alerts have a separate limit from the five stuck workers and five
  recent errors. Appropriate indexes on global serial and RF columns are needed
  for efficient checks; verify them before relying on frequent status calls.
  A failure status is returned when no execution is recorded in that period.
  Generic job and refresh statuses remain outside the report.
  A saved Oracle target that cannot be reached is reported as not connected.
  The complete result is also written to `report.md` at the repository root.
  Supply `slack_channel_id` to override that destination.
  The `MCP/Slack` Credential Manager token is used for delivery.
- `configure_daily_routine_schedule`: creates or updates the local Windows Task
  Scheduler task `\\OracleMCP\\DailyRoutine` for daily execution at 08:00. Its
  runner calls `daily_rutione_check`, prints the full result locally, and sends the configured default Slack DM.
- `set_saved_scheduled_task_run_whether_logged_on`: changes one Windows scheduled
  task on a saved host so it runs whether its account is logged on. The saved
  SSH password is sent on the remote process stdin and is not returned. The
  task keeps its existing account.
- `resolve_slack_channel`: resolves a visible Slack channel name (such as
  `essence`) to the ID required by `daily_rutione_check` notifications.
- `list_top_sql_memory`: ranks non-Oracle-maintained SQL by shared-pool memory
  (`SHARABLE_MEM + PERSISTENT_MEM + RUNTIME_MEM`).
- `list_local_postgres_databases`: lists every database on one saved
  PostgreSQL connection (default `local_postgres_admin`), including owner,
  encoding, size, and whether connections are allowed.
- `inspect_local_rag_database`: checks the local RAG PostgreSQL database,
  pgvector extension, and required RAG tables.
- `inspect_local_rag_ingestion_status`: reads document indexing timestamps and
  PostgreSQL session waits and blocking PIDs, without returning SQL or credentials.
- `ingest_local_rag_markdown`: ingests a Markdown or Python file, or directory,
  into the local PostgreSQL RAG database. Never ingest files containing secrets.
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
- `apply_proposed_site_indexes`: creates missing station-template, hub/transfer,
  report, and foreign-key supporting indexes from data dictionary metadata.
  New indexes are built ONLINE only; unsupported ONLINE builds are reported as
  errors and are never retried offline. Requires `confirmed=true`.
- `enqueue_saved_untransferred_products`: inserts `LAST_UUT_NAME` into the
  transfer log and queue, the same two writes the insert trigger performs.
  Only names present in `TRANSFER_PRODUCTS` and absent from both the log and
  the queue are included. It requires `confirmed=true`.
- `copy_saved_remaining_ph_units`: copies PH serials the refresh left out of
  `ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES`, including a repeated RF number and a
  listed product stored only as `FIRST_UUT_NAME`, and logs them as `PH`.
  Run it on the Spain connection. It requires `confirmed=true`.
- `copy_saved_hungary_units_by_rf`: copies only the listed Hungary RF numbers
  from `TRANSFER_USER.HUNGARY_UUT_ATTRUBUTES` into
  `ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES` and logs them as `Hungary`.
  Run it on the Spain connection. It requires `confirmed=true`.
- `copy_saved_hungary_remaining_units`: copies every Hungary MV row missing
  from `ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES` and logs the new serials as
  `Hungary`. Run it on the Spain connection. It requires `confirmed=true`.
- `force_saved_site_refresh`: refreshes one site's three materialized views
  (Hungary, Ofakim, RH, or PH) and copies every new UUT row and serial into
  the Spain global tables with no queue or cooldown gate, then writes the
  `DAILY_TRANSFER` audit record. Run it on the Spain connection. It requires
  `confirmed=true`.
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
- `copy_saved_schemas_with_datapump`: exports the named schemas with Data Pump
  into the source `PUMP_DIR` (or another directory object), zips the dump on
  that host, copies only the zip, extracts it into the target directory, and
  imports it. The copy stops before export when any named schema already
  exists on the target. Pass `confirmed=true` to run the export and import.
  Use `tablespace_remap` when the source tablespace is absent on the target.
- `copy_saved_schema_without_datapump`: copies one schema with
  `DBMS_METADATA` and row inserts. Stops before any change when that schema
  already exists on the target. Use this when Data Pump refuses the dump
  because the target timezone file is older. Pass `confirmed=true` to create
  the schema. The source password verifier is reused and never returned.
- Standalone Spain schema process (`schema_movement_process.py`): run from
  `myoracle_mcp` with saved `.db/connections.json`. `copy` defaults to Spain
  (`es_db2_orclsp_sys`) and remaps site tablespaces to `SPAIN_TBS`;
  `deploy-to-spain` uploads the Python bundle to `C:\ORCL\schema_movement` on
  the Repair Center host. Example:
  `python schema_movement_process.py copy --source RH --schema ATE_RESULTS`
  (plan only) and add `--confirmed` to apply.
- `sync_saved_package_overloads`: copies every overload of one packaged
  procedure from a source database into the same package on a target. The
  other procedures in the target package stay in place. Pass `confirmed=true`
  to replace the package. Optional `trigger_owner` and `trigger_name` compile
  that trigger afterward.
- `run_saved_oracle_query`: runs one read-only `SELECT`/`WITH` statement on a
  saved Oracle connection and returns columns plus up to `max_rows` rows
  (1-5000, default 500). Statements containing DML, DDL, `FOR UPDATE`,
  PL/SQL calls, or extra statements are rejected before connecting. Uses the
  saved host unless `host` (and optionally `port`) is overridden. Pass
  `service_name` to override the saved service (empty string connects by
  SID), or `sid` to override the saved SID; overridden runs persist nothing.
- `gather_saved_exact_table_statistics`: gathers optimizer statistics for
  every non-Oracle-maintained table on one to four saved connections at the
  same time. Each table uses ``DBMS_STATS.GATHER_TABLE_STATS`` with
  ``estimate_percent`` (default 100) and parallel ``degree`` (default 10).
  At 100 the returned row count is a full count. ``unlock_statistics`` unlocks
  each table before gathering it, and ``locked_only`` limits the run to tables
  whose statistics are already locked. Temporary, nested, external, secondary,
  recycle-bin, and ``$`` names are skipped. Each connection stops starting new
  tables after ``timeout_seconds`` (maximum 10800, three hours). It requires
  ``confirmed=true``. The call returns as soon as the work has started.
  Per-table progress is appended under ``reports/exact_table_stats/``.
  ``resume=true`` skips tables already recorded there.
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
