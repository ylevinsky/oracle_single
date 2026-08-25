# FPY_WEEKLY rewrite 4 deferred: running job and non-unique source match

- Request and scope: apply only the proposed rewrite that replaces four child-table LEFT JOIN / COALESCE existence checks with EXISTS predicates in `EREPORTS.TESTYIELDREPORT_TRY`.
- Live blocker: `SYS.FPY_WEEKLY` on FLEX remains `RUNNING`, started 2026-08-18 14:40:43 +03:00; package replacement must not be performed during the active production execution.
- Source-scope blocker: the candidate `COALESCE (C.ID,P.ID,M.ID,O.ID,0) > 0` expression occurs seven times in the current package body. A broad textual replacement would alter multiple report paths and violate the requested single-scope change.
- Outcome: no package source, job, index, statistics, or data was changed.
- Required safe next step: after the active job completes, identify the exact procedure and each intended occurrence by source line/context, then obtain approval for the explicit occurrence count and compile the revised package body.