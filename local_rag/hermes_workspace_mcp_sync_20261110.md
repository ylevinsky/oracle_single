# Hermes workspace MCP sync — 2026-11-10

- Goal: connect the same MCP servers Cursor/Codex use (`super-mcp`, `myoracle`) to Hermes Agent.
- Implementation: `temp_scripts/sync_mcp_servers_to_hermes.py` merges JSON MCP definitions into `~/.hermes/config.yaml` under `mcp_servers`; `register-workspace-mcp-for-hermes.ps1` wraps sync plus optional `hermes mcp test`.
- Source file: `workspace-agent/.mcp.json` (stdio commands are Windows absolute paths; run the scripts on the Windows workstation, not the Linux cloud agent).
- Hermes does not persist `cwd` from Cursor MCP JSON; `super-mcp` and `myoracle` launchers use absolute paths in `command`/`args` instead.
- Security: no credentials added; sync only copies command/args/env from existing MCP JSON.
