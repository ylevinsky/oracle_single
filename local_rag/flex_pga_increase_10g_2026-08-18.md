# FLEX PGA increase to 10G completed without restart

- Request and scope: increase `PGA_AGGREGATE_TARGET` to 10G on FLEX without reboot. User explicitly approved the required companion increase of `PGA_AGGREGATE_LIMIT` to 20G.
- Prior rejection: `ORA-02097` / `ORA-00856` required the target to be no more than 50 percent of the aggregate limit; 15G with an 18G limit was rejected and made no change.
- Applied changes: `ALTER SYSTEM SET PGA_AGGREGATE_LIMIT = 20G SCOPE=BOTH`, then `ALTER SYSTEM SET PGA_AGGREGATE_TARGET = 10G SCOPE=BOTH`.
- Verified outcome: limit changed from 18G to 20G; target changed from 8G to 10G; both were immediately effective and persisted; no restart was required.
- MCP change: added confirmation-gated `set_saved_pga_aggregate_limit` and corrected the target setter to enforce Oracle's 50-percent rule before issuing DDL.