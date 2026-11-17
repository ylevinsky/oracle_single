# Hermes RH connection discovery — 2026-11-17

- Symptom: Hermes reported no Oracle connection for RH; it did not map “Repair Center” / `rh` to saved key `RH`.
- Root cause: Hermes had no myoracle MCP bridge (scripts were only on an unmerged branch) and agents guessed connection names instead of calling `connections_list` / `oracle_sites_index`.
- Fix: `connection_store.resolve_connection_name` aliases (`rh`, `repair center` → `RH`); `oracle_sites_index` tool; portable `run_stdio` launchers with `MYORACLE_REPOSITORY_ROOT`; Hermes sync script `temp_scripts/sync_mcp_servers_to_hermes.py` and `register-workspace-mcp-for-hermes.ps1`; committed `.db/connections.json.example`.
- User action on Windows: `.\temp_scripts\register-workspace-mcp-for-hermes.ps1 -Test`, then restart `hermes chat`.