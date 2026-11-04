---
name: find-myoracle-mcp
description: Locate and verify availability of the local myoracle MCP server, list its tools, and call them via super-mcp. Use when the user asks whether myoracle or the local MCP server is available, when Oracle operational work needs the myoracle tool route, or when troubleshooting MCP connectivity for this repository.
---

# Find the myoracle MCP server

The myoracle server is `oracle_single/myoracle_mcp/server.py` (`FastMCP`), run with
`oracle_single/myoracle_mcp/.venv/Scripts/python.exe`. Its config lives in
`oracle_single/.cursor/mcp.json`, which Cursor does **not** load when the workspace
root is `C:\git` (no root-level `mcp.json`). The working route is therefore the
**super-mcp** package `myoracle`, which launches the same server command.

## Check availability

1. Discover the super-mcp tool schema first (schemas can change between sessions):

   Call `GetDynamicTools` with `namespace: "user-super-mcp"`.

2. Check health of just the myoracle package:

   Call `user-super-mcp` → `health_check` with `{"package_id": "myoracle"}`.
   `status: "ok"` means the package is connected and authenticated.

3. Prove the server responds live:

   Call `user-super-mcp` → `list_tools` with
   `{"package_id": "myoracle", "detail": "lite"}`. A tool list (20+ tools,
   tool IDs like `myoracle__connections_list`) is stronger evidence than the
   health flag alone.

Report both results: reachable via super-mcp, direct **myoracle** stdio in Codex/VS Code configs (required for agents to list Oracle tools without calling `use_tool`), and (usually) not registered as a
direct Cursor namespace when only super-mcp is configured at workspace root without `.cursor/mcp.json`.

## Call a myoracle tool

1. `get_tool_details` with the tool ID (for example `myoracle__check_saved_oracle_connectivity`)
   to hydrate the exact argument schema.
2. `use_tool` with `{"package_id": "myoracle", "tool_id": "myoracle__<name>", "args": {...}}`.

Tool-specific arguments go inside `args` only — `max_output_chars`, `dry_run`,
`schema_hash`, and `result_id` are top-level `use_tool` parameters.

## Check for a direct Cursor namespace (optional)

Call `GetDynamicTools` with `pattern: "oracle|myoracle"`. An empty match confirms
no direct namespace exists.

## Troubleshooting

- **`health_check` shows an error for `myoracle`** — read the returned
  `suggested_actions`, then try `user-super-mcp` → `restart_package` with
  `{"package_id": "myoracle"}` and check again.
- **No `user-super-mcp` namespace at all** — verify `~/.cursor/mcp.json` still
  registers `super-mcp`; that is where it is launched from.
- **User wants a direct namespace (no super-mcp hop)** — add the server entry to
  `C:\git\.cursor\mcp.json` and register **`myoracle`** in `~/.codex/config.toml` / `.vscode/mcp.json`
  (see `AGENTS.md`). super-mcp alone only exposes router meta-tools (`use_tool`, `list_tools`), which
  VS Code Codex may not treat as “Oracle MCP available”.

## Related

- For adding new tools to the server, use the `add-myoracle-tool` skill instead.