## oracle_single Git remote

- Connection type: HTTPS Git remote
- Reuse details: remote `origin` at `github.com/ylevinsky/oracle_single`, branch `main`; verified 2026-09-15 by pushing commit `927e103`.
- Credential reference: Git Credential Manager for the signed-in GitHub account; no token is stored in this file.

## Hermes ↔ myoracle MCP (Windows)

- Repair Center Oracle is saved connection **`RH`** in `.db/connections.json` (template: `.db/connections.json.example`).
- Hermes must register **myoracle**: `.\temp_scripts\register-workspace-mcp-for-hermes.ps1 -Test`, then a new `hermes chat` session.
- Tools: `oracle_sites_index`, `connections_list`, `check_saved_oracle_connectivity` with `RH`.
