# RMAN monitoring input type removal

- User request and scope: remove the `INPUT_TYPE` column from all daily routine backup-monitoring queries.
- Implementation: `myoracle_mcp/server.py` now selects only session key, status, start/end timestamps, and displayed size from `V$RMAN_BACKUP_JOB_DETAILS`. Completed backup monitoring remains based on `V$BACKUP_SET_DETAILS.INCREMENTAL_LEVEL` (level 0 within 14 days; level 1 within three days). Failed job alerts no longer return or display input type.
- Verification: compilation succeeded and `python -m unittest test_server.py` passed all 17 tests. The regression test verifies that both completed and failed SQL do not contain `input_type` and that failed-alert field mapping remains correct.
- Security: no credentials, connection strings, or backup contents were recorded.
