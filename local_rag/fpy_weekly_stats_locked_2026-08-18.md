# FLEX FPY_WEEKLY stale statistics collection blocked

- Request and scope: gather optimizer and dependent-index statistics for stale `SYSTEM_ATE_2.STEP_STRINGVALUE`, `STEP_PASSFAIL`, and `MEAS_NUMERICLIMIT` on FLEX.
- Exact error for all three tables: `ORA-20005: object statistics are locked (stattype = ALL)` from `SYS.DBMS_STATS`.
- Verified outcome: no table or index statistics changed; all statistic locks remain intact.
- Current blocker: statistics must be explicitly unlocked by the data owner or approved maintenance authority before `DBMS_STATS.GATHER_TABLE_STATS` can proceed. Do not unlock automatically while the FPY_WEEKLY job is running.
- Related diagnosis: stale 2021 statistics continue to reduce plan reliability for the wide outer-join SQL, but the immediate highest-value fix remains removal of the min/max `STEP_RESULT` range join.