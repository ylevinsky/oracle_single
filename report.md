# Daily Routine Report

Generated: 2026-11-03T12:37:00+02:00
Minimum free space threshold: 15.00%

## Summary

- Targets checked: 7
- OK: 0
- Issues: 6
- Failed: 1

## Target details

### DWH — FAILED

- Connection error: `OperationalError: DPY-6005: cannot connect to database (CONNECTION_ID=61axyetkp5jcAi7uGK7pTQ==).
timed out`

### DWH_CL — ISSUES

**Tablespace capacity alerts**

- `FLEXDWH_CL`: 14.99% free (free_percent_below_threshold)

**Backup alerts**

```json
[
  {
    "type": "missing_full",
    "incremental_level": 0,
    "days": 14
  },
  {
    "type": "missing_incremental",
    "incremental_level": 1,
    "days": 3
  }
]
```

**Alert-log alerts**

```json
[
  {
    "type": "alert_log_check_failed",
    "error": "ValueError: Connection 'DWH_CL' needs an ssh_username before SSH use"
  }
]
```

### FLEX — ISSUES

**Tablespace capacity alerts**

- `OFAKIM_TBS`: 14.98% free (free_percent_below_threshold)

**Alert-log alerts**

```json
[
  {
    "type": "alert_log_error",
    "code": "TNS-12170",
    "count": 200
  }
]
```

### HUN — ISSUES

**Alert-log alerts**

```json
[
  {
    "type": "alert_log_error",
    "code": "TNS-12170",
    "count": 157
  },
  {
    "type": "alert_log_error",
    "code": "TNS-12637",
    "count": 2
  },
  {
    "type": "alert_log_error",
    "code": "ORA-609",
    "count": 1
  }
]
```

### PH — ISSUES

**Alert-log alerts**

```json
[
  {
    "type": "alert_log_error",
    "code": "TNS-12170",
    "count": 196
  }
]
```

### RH — ISSUES

**Alert-log alerts**

```json
[
  {
    "type": "alert_log_check_failed",
    "error": "NoValidConnectionsError: [Errno None] Unable to connect to port 22 on 10.102.0.4"
  }
]
```

### es_db2_orclsp_sys — ISSUES

**Tablespace capacity alerts**

- `SPAIN_TBS`: 14.79% free (free_percent_below_threshold)

**Alert-log alerts**

```json
[
  {
    "type": "alert_log_error",
    "code": "TNS-12170",
    "count": 131
  },
  {
    "type": "alert_log_error",
    "code": "ORA-06512",
    "count": 81
  },
  {
    "type": "alert_log_error",
    "code": "ORA-12012",
    "count": 27
  },
  {
    "type": "alert_log_error",
    "code": "ORA-38153",
    "count": 27
  },
  {
    "type": "alert_log_error",
    "code": "ORA-12008",
    "count": 10
  },
  {
    "type": "alert_log_error",
    "code": "ORA-3136",
    "count": 5
  },
  {
    "type": "alert_log_error",
    "code": "ORA-0",
    "count": 2
  },
  {
    "type": "alert_log_error",
    "code": "ORA-609",
    "count": 2
  },
  {
    "type": "alert_log_error",
    "code": "TNS-12547",
    "count": 2
  }
]
```

**Refresh/job alerts**

```json
[
  {
    "type": "refresh_mv_error",
    "started_at": "2026-11-02 14:00:03",
    "ended_at": "2026-11-02 14:00:07",
    "error": "DatabaseError: ORA-12008: error in materialized view or zonemap refresh path ORA-06512: at \"SYS.DBMS_SNAPSHOT_KKXRCA\", line 3012 ORA-06512: at \"SYS.DBMS_SNAPSHOT_KKXRCA\", line 2424 ORA-01555: snapshot too old: rollback segment number 4 with name \"_SYSSMU4_2372004640$\" too small ORA-02063: precedi..."
  },
  {
    "type": "refresh_mv_error",
    "started_at": "2026-11-02 14:00:03",
    "ended_at": "2026-11-02 14:00:10",
    "error": "DatabaseError: ORA-12008: error in materialized view or zonemap refresh path ORA-06512: at \"SYS.DBMS_SNAPSHOT_KKXRCA\", line 3012 ORA-06512: at \"SYS.DBMS_SNAPSHOT_KKXRCA\", line 2424 ORA-01555: snapshot too old: rollback segment number 10 with name \"_SYSSMU10_3563521556$\" too small ORA-02063: prece..."
  },
  {
    "type": "refresh_mv_error",
    "started_at": "2026-11-01 20:00:04",
    "ended_at": "2026-11-01 20:00:10",
    "error": "DatabaseError: ORA-12008: error in materialized view or zonemap refresh path ORA-06512: at \"SYS.DBMS_SNAPSHOT_KKXRCA\", line 3012 ORA-06512: at \"SYS.DBMS_SNAPSHOT_KKXRCA\", line 2424 ORA-01555: snapshot too old: rollback segment number 3 with name \"_SYSSMU3_3193270435$\" too small ORA-02063: precedi..."
  },
  {
    "type": "refresh_mv_error",
    "started_at": "2026-11-01 20:00:04",
    "ended_at": "2026-11-01 20:00:08",
    "error": "DatabaseError: ORA-12008: error in materialized view or zonemap refresh path ORA-06512: at \"SYS.DBMS_SNAPSHOT_KKXRCA\", line 3012 ORA-06512: at \"SYS.DBMS_SNAPSHOT_KKXRCA\", line 2424 ORA-01555: snapshot too old: rollback segment number 6 with name \"_SYSSMU6_3809612316$\" too small ORA-02063: precedi..."
  }
]
```

