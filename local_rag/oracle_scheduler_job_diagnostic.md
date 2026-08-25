# Oracle Scheduler Job Diagnostic

- Date: 2026-08-18
- User request: investigate `FPY_WEEKLY` on the Ofakim/FLEX database, including why it failed and its purpose.
- Target scope: saved `FLEX` Oracle connection and Scheduler job name `FPY_WEEKLY`.
- Diagnostic gap: the existing Scheduler-history search matched only text in `ADDITIONAL_INFO` and `OUTPUT`, so it could not find a job by its job name or return its definition.
- Feature created: `inspect_saved_scheduler_job(connection_name, job_name, history_days=30)` in `C:\git\ORCL\oracle_connectivity_mcp\server.py`.
- Read-only evidence: `DBA_SCHEDULER_JOBS` definition fields, including job action, recurrence, enabled state, run/failure counts, and every `DBA_SCHEDULER_JOB_RUN_DETAILS` row in the selected 1-to-365-day date window.
- First-run error: `DPY-3022: named time zones are not supported in thin mode` while fetching Oracle Scheduler timestamp-with-time-zone columns.
- Verified solution: convert `START_DATE`, `NEXT_RUN_DATE`, `LAST_START_DATE`, `LOG_DATE`, `REQ_START_DATE`, and `ACTUAL_START_DATE` with `TO_CHAR(..., 'YYYY-MM-DD HH24:MI:SS TZH:TZM')` in the tool queries; this keeps the tool read-only and avoids thin-driver time-zone conversion.
- Verified live result: `SYS.FPY_WEEKLY` is enabled and scheduled weekly each Sunday. It executes `BEGIN EREPORTS.TESTYIELDREPORT_TRY.SCHEDULEDYIELDREPRT(); END;` to generate weekly first-pass-yield data in `YIELD_SUM_REPORT` from `SYSTEM_ATE_2` UUT and step-result data.
- Failure diagnosis: the 2026-08-16 run failed after 2 hours 23 minutes 49 seconds with `ORA-06580: Hash Join ran out of memory while keeping large rows in memory`, from `EREPORTS.TESTYIELDREPORT_TRY` lines 1240, 1707, and 1802. The failure is database work-area memory pressure during the report insert, not a Scheduler configuration failure.
- Current Scheduler state: enabled, `SCHEDULED`, next run 2026-08-23 12:23:49 +03:00, 104 total runs, and 3 failures. The preceding four weekly runs succeeded.
