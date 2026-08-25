# FLEX PGA target change rejected by Oracle

- Request and scope: set `PGA_AGGREGATE_TARGET=15G` on FLEX immediately and persistently, without reboot.
- Exact error: `ORA-02097: parameter cannot be modified because specified value is invalid` and `ORA-00856: PGA_AGGREGATE_TARGET cannot be set higher 50 percent of PGA_AGGREGATE_LIMIT.`
- Verified outcome: no instance parameter changed. The existing `PGA_AGGREGATE_TARGET=8G` and `PGA_AGGREGATE_LIMIT=18G` remain in effect.
- Blocker and solution: Oracle requires an aggregate limit of at least `30G` before a `15G` target can be set. The exact persistent change scope, if approved, is `ALTER SYSTEM SET PGA_AGGREGATE_LIMIT = 30G SCOPE=BOTH`, followed by `ALTER SYSTEM SET PGA_AGGREGATE_TARGET = 15G SCOPE=BOTH`; neither needs a reboot.
- MCP change: the new target setter currently validates only target <= limit and missed Oracle's 50-percent rule. It is intentionally not committed pending a decision to correct the validation and apply the required limit change.