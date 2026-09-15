# myoracle stdio orphan-process fix

- Recorded: 2026-09-15
- User request: Fix the Codex/Super-MCP error where windows remain open or processes are abandoned, and restore the Oracle diagnostic tool.
- Scope: Super-MCP package `myoracle` and its Windows stdio launcher.
- Verified failure: Super-MCP reported `MCP error -32000: Connection closed` while discovering `myoracle`. Each failed attempt left an orphaned `uv -> venv Python -> uv-managed Python` tree running `C:\git\oracle_single\myoracle_mcp\server.py`.
- Root cause: The live router package registry retained a PowerShell launcher that synchronously invoked `uv run`; its config watcher only reloads security policy, not `mcpServers` package entries. `restart_package` therefore continued to use the original in-memory launcher definition.
- Applied fix: Updated `C:\Users\brillix\.super-mcp\config.json` so `myoracle` launches `C:\git\oracle_single\myoracle_mcp\.venv\Scripts\python.exe` directly with `C:\git\oracle_single\myoracle_mcp\server.py` as its sole argument. This eliminates the PowerShell and `uv` intermediary processes and keeps the stdio server child attached to the router without opening a console window.
- Cleanup: Terminated only the verified orphan `myoracle` process trees and then stopped the old Super-MCP router so a new process can load the corrected package definition.
- Verification: JSON and direct command paths were validated; `server.py` compiled successfully. The prior router transport closed as expected after shutdown. A VS Code/Codex window reload is required to start a new router and complete a live discovery/tool-call test.
- Credentials: No credential values were recorded.
