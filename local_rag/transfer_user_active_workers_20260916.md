# Spain DAILY_TRANSFER active worker explanation

- User question: why only Hungary and Ofakim are running in the Spain refresh process.
- Read-only Super-MCP diagnostic at 2026-09-16 local time: `refresh_mv.py` starts one multiprocessing worker for each configured site (Ofakim, Hungary, and RH). RH completed the current cycle from 2026-09-15 23:56:13 through 23:56:55, so it no longer has an active `DAILY_TRANSFER_PY` session.
- Current state: Hungary and Ofakim were the two remaining active workers. Both were active on `SQL*Net more data from dblink` with Network wait class and zero seconds in wait; no active long operations were returned. This indicates data is currently arriving over their database links, not a demonstrated hang.
- Safety: read-only diagnostic; no credentials or application data recorded.
