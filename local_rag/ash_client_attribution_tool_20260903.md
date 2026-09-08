# ASH client attribution tool

- Date: 2026-09-03
- Request: Add a tool to identify which Oracle client machine, user, program, and module contributed most heavily to concurrent activity.
- Scope: Read-only `myoracle` MCP tool for saved Oracle targets.
- Implementation: `inspect_saved_ash_client_attribution` queries `DBA_HIST_ACTIVE_SESS_HISTORY`, joins `DBA_USERS`, groups by username, machine, program, module, action, and SQL ID, and returns sample and distinct-session counts.
- Safety: ISO time range is required and limited to seven days; result limit is capped at 100; no credentials or SQL text are returned.
- Interpretation: ASH sample counts show observed active-session activity and do not prove exact session creation counts.
- Verification: Python compilation succeeded and the live Super-MCP catalog exposed `myoracle__inspect_saved_ash_client_attribution` after package reload.
- Handled error: Ingestion from outside the repository was rejected with `path must remain inside the repository`; the record was moved under the permitted repository root before retrying.
- Follow-up: `CONTROL_MANAGEMENT_PACK_ACCESS` was changed from `NONE` to `DIAGNOSTIC` with `SCOPE=BOTH` on DWH_CL, FLEX, HUN, PH, and RH without restarting those databases. Spain was already enabled.
- Failure: DWH returned sanitized error `DPY-6005: cannot connect to database; timed out`; no parameter change was made on DWH.
- AWR generation attempt: Spain requests for 16:00-17:00 and 17:00-18:00 on 2026-09-03 failed with `ORA-20019` because snapshots 33141 and 33142 span a database restart. Snapshot inspection confirmed no boundaries exist during 16:00-18:00; reports were not created.
- PGA change blocker: Requested `init_yuri.ora` was not found on Spain. The host has `C:\oracle19c\database\SPFILEORCLSP.ORA` as the current parameter file and `INITORCLSP.ORA` as an older text PFILE. No PGA change was made pending confirmation of the intended backup file.
