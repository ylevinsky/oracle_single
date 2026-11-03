# Daily routine backup status - 2026-09-15

- Request and scope: remove schema-copy artifacts from the daily Oracle routine report and add per-target backup status.
- Code change: `daily_rutione_check` now excludes jobs owned by `COPY_SCHEMA` and any Scheduler or legacy action containing `DBMS_DATAPUMP`. It independently collects a compact `backup` status for every saved target and marks unavailable backup verification explicitly.
- Verification: Python compilation and nine unit tests passed. The `myoracle` package was restarted and the live Super-MCP routine ran successfully across seven saved targets.
- Live result: Spain `job_issues` no longer included `COPY_SCHEMA` or Data Pump probe artifacts. Backup status appeared on all targets. DWH and DWH_CL backup checks were unverified because their saved connections have no SSH username. FLEX backup checks were unverified because `F:/Backup/Oracle/RMAN` was not found. The remaining target statuses were returned by the routine but are point-in-time.
- No corrective Oracle, backup, or Scheduler action was taken. Commit `73d62bd` was pushed to `main`.
- RAG indexing status: routed ingestion did not return after one minute and was terminated. This local sanitized record is retained, but its indexed status is unverified.
