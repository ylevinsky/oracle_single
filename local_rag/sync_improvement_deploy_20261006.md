# Sync improvement implementation and Spain deployment — 2026-10-06

- Finding: Hungary (SID 1833) and Ofakim (SID 1835) `DAILY_TRANSFER_PY` workers stuck
  ~90h in `SQL*Net more data from dblink` on full `MV_REFRESH (INS)` inserts; nightly
  retries piled `DPY-4024` 3h call-timeout `Error` rows into `TRANSFER_USER.LOG_PROCEDURE`
  while the orphaned server sessions kept running. PH/RH stayed healthy (~45s).
- Fix: killed both stuck sessions via `kill_saved_oracle_session`; re-check showed
  `active_workers: []`.
- `ORCL/refresh_mv.py`: TOML-driven timeouts/retries (`_refresh_settings`), stale-session
  kill + verify after each failed attempt (`_kill_stale_site_sessions`), 6h overall deadline
  (`overall_deadline_hours`), site-tagged `Error` rows, per-MV commit with
  `atomic_refresh => false` + `MV_REFRESH` timing, set-based `_copy_uuts`/`_copy_serials`
  with bulk log inserts and rowcounts.
- `ORCL/refresh_mv_support.py` + `refresh_mv.toml`: new `overall_deadline_hours = 6.0`;
  effective per-attempt timeout is now the TOML value (2h, was hardcoded 3h).
- Dead MVs retired: `TRANSFER_USER.OFAKIM_UUT_ATTRUBUTES` (last refresh 2025-11-02) and
  `TRANSFER_USER.OFAKIM_NKEYS_ALLOCATED2` (last refresh 2026-07-20) — DDL archived in
  `ORCL/ddl/retired/`, dropped via new `drop_saved_materialized_view` tool
  (`oracle_single/myoracle_mcp/object_retire.py`) after verifying zero dependents.
- Monitoring: `inspect_saved_sync_process_status` reports `stuck`/`stuck_workers`/per-site
  `sites` map (`stuck_threshold_seconds`, default 7200); `_spain_refresh_mv_alerts`
  emits `refresh_mv_stuck` alerts. Unit suite 76/76 green.
- Spain deploy: backed up remote files to `backups/20261006_174806/`, uploaded the three
  files, remote SHA-256 matches local exactly, remote `py_compile` passes, `__pycache__`
  cleared. No refresh was running during deploy; next scheduled run 22:00.
- Safety: no credentials recorded; DDL exports contain no row data.
