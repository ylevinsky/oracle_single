# PostgreSQL Service Start Blocker

- Date: 2026-08-18
- User request: stop the manually started PostgreSQL instance and start the registered Windows service.
- Target: PostgreSQL service `postgresql-x64-18` and data directory `C:\Program Files\PostgreSQL\18\data`.
- Completed action: `pg_ctl stop -D C:\Program Files\PostgreSQL\18\data -m fast -w -t 30` returned `server stopped`.
- Rejected action: `Start-Service -Name postgresql-x64-18`.
- Exact sanitized error: `Cannot open postgresql-x64-18 service on computer '.'.`
- Current blocker: this shell is not elevated; starting the registered Windows service requires Administrator rights.
- Required solution: run `Start-Service -Name postgresql-x64-18` from the elevated PowerShell session used to register the service, then verify `Get-Service postgresql-x64-18` reports `Running`.
- Feature/code change: none; this is Windows service control.
- RAG indexing status: pending because PostgreSQL is stopped.
