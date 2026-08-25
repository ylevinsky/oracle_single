# FPY_WEEKLY Hash Join Memory Remediation

- Date: 2026-08-18
- User request: determine how to fix the failed `SYS.FPY_WEEKLY` job on FLEX.
- Target scope: `EREPORTS.TESTYIELDREPORT_TRY.SCHEDULEDYIELDREPRT` and its weekly `YIELD_SUM_REPORT` insert.
- Verified failure: 2026-08-16 run raised `ORA-06580: Hash Join ran out of memory while keeping large rows in memory`, with package-stack lines 1240, 1707, and 1802.
- Verified workload: the logged SQL builds a weekly `TEMP_SERIAL` CTE from `SYSTEM_ATE_2_UUT_RESULT`, joins `SYSTEM_ATE_2_STEP_RESULT` and its step-detail tables, then inserts aggregated first-pass-yield data into `YIELD_SUM_REPORT`.
- Current blocker: the exact failing hash-join operator and its estimate/actual-row mismatch have not been captured, so no production SQL or memory change is verified.
- Recommended sequence: capture the execution plan and row estimates for the failed insert; gather stale optimizer statistics on the participating tables and indexes; ensure join-key indexes exist, especially `SYSTEM_ATE_2_STEP_RESULT(UUT_RESULT)` and each step-detail table's `STEP_RESULT` key; then rewrite or batch the weekly insert if the plan still chooses a memory-heavy hash join. Prefer joining the selected serial set before wide step-detail joins and review whether the broad min/max-ID range join is creating excess intermediate rows.
- Escalation option: increase available PGA/work-area memory only after measuring current capacity and confirming the plan/data fixes are insufficient. This is a database-wide configuration change and requires explicit approval.
- Verification status: no production fix has been applied or verified.
