# Daily routine RMAN incremental-level checks

- User request and scope: change the daily routine RMAN full and incremental backup queries so they check backup incremental level rather than RMAN job `INPUT_TYPE`.
- Implementation: `myoracle_mcp/server.py` now joins `V$RMAN_BACKUP_JOB_DETAILS` to `V$BACKUP_SET_DETAILS` on `SESSION_KEY`. The 14-day full check requires `INCREMENTAL_LEVEL = 0`; the three-day incremental check requires `INCREMENTAL_LEVEL = 1`. Failed RMAN jobs from the last 14 days remain reported independently.
- Verification: `python -m py_compile server.py test_server.py` completed successfully and `python -m unittest test_server.py` passed 14 tests.
- Handled test error: the first regression-test run returned no alerts because the mock database context manager did not return its configured cursor. The fixture was corrected by setting its `__enter__` return value; the production implementation was unchanged and the full suite then passed.
- Live Super-MCP validation: after package reload, `daily_rutione_check` completed against six reachable saved targets and Slack delivery returned `delivered: true` with one message. The level-0 and level-1 checks returned expected alert structures where applicable. DWH was unverified because its Oracle connection timed out (`DPY-6005`); no conclusion was drawn for that target.
- Handled router invocation error: the first live call used an obsolete `use_tool` argument shape and was rejected before dispatch because `tool_id` was missing. The documented `myoracle__daily_rutione_check` tool ID was retrieved and the next call succeeded.
- Security: no credentials, Slack token, database connection string, or backup contents were recorded.
