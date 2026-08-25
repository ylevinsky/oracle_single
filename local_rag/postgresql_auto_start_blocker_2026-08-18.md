# PostgreSQL Automatic Startup Blocker

- Date: 2026-08-18
- User request: start local PostgreSQL and make it start automatically.
- Target: PostgreSQL 18 data directory `C:\Program Files\PostgreSQL\18\data`.
- Current outcome: PostgreSQL was started successfully with `pg_ctl start`; no PostgreSQL Windows service is registered.
- Rejected operation: `pg_ctl register -N postgresql-x64-18 -D C:\Program Files\PostgreSQL\18\data -S auto`.
- Exact sanitized error: `pg_ctl: could not open service manager`.
- Related diagnostic rejection: querying the PostgreSQL process account returned `Get-Process : The 'IncludeUserName' parameter requires elevated user rights.`
- Current blocker: this session is not elevated, and Windows service registration requires Administrator rights.
- Required solution: run the same `pg_ctl register` command from an elevated PowerShell session, then verify service `postgresql-x64-18` is Automatic and Running.
- Feature/code change: none; this is Windows service configuration.
