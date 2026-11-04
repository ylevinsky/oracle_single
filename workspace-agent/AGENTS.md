# C:\git workspace agent rules

These rules apply in **Cursor** (`.cursor/rules/`), **Codex in VS Code** (`AGENTS.md` + skills/hooks/plugins), and via **super-mcp** (Oracle and other MCP tools).

## Oracle operational work (always apply)

Operational work goes through the local MCP server at `oracle_single/myoracle_mcp/server.py`. That includes Oracle queries, saved connections, alert logs, SSH on saved hosts, backups, and related checks.

- Discover and call existing `@mcp.tool()` functions through **super-mcp** package `myoracle` (preferred) or the direct `myoracle` MCP namespace when registered.
- Do not open a saved connection from a one-off script, `sqlplus`, or a private import of `server.py`.
- If no tool can perform the task, add that tool before doing the work another way, then finish the original task by calling the new tool. Use the **`add-myoracle-tool`** skill (`.cursor/skills/` and `.github/skills/`).

## Generated Python belongs in the MCP server

The local MCP server is `oracle_single/myoracle_mcp/server.py` (`FastMCP`). A new Python file is not finished until that server can run it.

- Put the module under `oracle_single/myoracle_mcp/`.
- Do not leave a one-off script in `ORCL/` or a temp path as the only way to run the new code.
- Never create or run `myoracle_mcp/a.py`. The RH connection check is the `check_saved_oracle_connectivity` tool.
- Hooks under `.cursor/hooks/` and `.github/hooks/myoracle-guard/` enforce this in Cursor and Codex.

## MCP routing

| Client | How myoracle is reached |
|--------|-------------------------|
| Cursor (this repo) | **`myoracle`** stdio in `.cursor/mcp.json` (direct tools), or **`super-mcp`** → package `myoracle` |
| Codex / VS Code | **`myoracle`** stdio in `~/.codex/config.toml` and workspace `.vscode/mcp.json` / `.mcp.json` (direct tools Codex can list); **`super-mcp`** for other packages |
| Troubleshooting | `find-myoracle-mcp` skill; `codex mcp list` should show **myoracle** and **super-mcp**; `user-super-mcp` → `health_check` with `package_id: myoracle` |

Sub-repositories (`oracle_single`, `ORCL`) may add their own `.codex/config.toml`; the workspace root config above applies when the folder opened is `C:\git`.

## After changing MCP or plugins

Reload **VS Code** (Developer: Reload Window) and restart **Codex** so `~/.codex/config.toml` and workspace `.mcp.json` / `.vscode/mcp.json` are picked up. If Codex reports config errors, run `codex doctor` — duplicate `[plugins."…"]` keys in `config.toml` will prevent all MCP from loading.

- **Project skills**: `.cursor/skills/` (Cursor) and the **`git-oracle-agent@git-agent`** Codex plugin (junctions to the same skill folders).
- **Project hooks**: `.cursor/hooks.json` (Cursor) and `.github/hooks/myoracle-guard/` (Codex).
- **Cursor plugins** (Harness, Mem0, Slack, etc.): MCP endpoints are also registered in `~/.super-mcp/config.json` for Codex/VS Code via super-mcp; install matching **Codex plugins** from the same vendor when skills/hooks are required (see `scripts/register-codex-agent-parity.ps1`).
