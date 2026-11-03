# STATISTICS_LEVEL ALL attempt across saved Oracle targets

- User request: set Oracle STATISTICS_LEVEL to ALL on all saved Oracle servers.
- Scope: DWH, DWH_CL, FLEX, HUN, PH, RH, and es_db2_orclsp_sys.
- Implementation: deployed repository MCP tool set_saved_statistics_level using ALTER SYSTEM SET STATISTICS_LEVEL='ALL' SCOPE=BOTH with live-value verification.
- Outcome: no target was changed because every connection failed before SQL execution.
- Sanitized errors: DWH, DWH_CL, FLEX, HUN, RH, and es_db2_orclsp_sys returned Windows DNS resolution error [Errno 11001] getaddrinfo failed; PH returned DPY-6005 connection timeout.
- Repository change: commit 48a3180 added the MCP setter and package reload exposed it.
