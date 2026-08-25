# FPY_WEEKLY manual retry after index creation

- Request and scope: retry failed `SYS.FPY_WEEKLY` on FLEX after creating `SYSTEM_ATE_2.IX_UUT_RESULT_SERIAL_START`; normal job inserts were explicitly authorized for this one manual retry.
- Prior failure: `ORA-06580: Hash Join ran out of memory while keeping large rows in memory`, with `EREPORTS.TESTYIELDREPORT_TRY` stack lines 1240, 1707, and 1802.
- Action: Oracle MCP submitted `DBMS_SCHEDULER.RUN_JOB` for `SYS.FPY_WEEKLY` asynchronously on 2026-08-18. The job was enabled and `SCHEDULED` before submission; no existing running instance was found.
- Outcome at submission: `status: submitted_asynchronously`. Completion must be determined from Scheduler run history after the execution finishes.
- MCP feature: added confirmation-gated `run_saved_scheduler_job`, restricted to an existing enabled owner-qualified job and rejecting active duplicate execution.