---
name: add-myoracle-tool
description: Add a new tool to the local myoracle MCP server (oracle_single/myoracle_mcp). Use when creating any Python module for this repository, registering an @mcp.tool() in server.py, or when an Oracle operational task needs a capability no existing myoracle tool supports.
---

# Add a myoracle MCP tool

The local MCP server is `oracle_single/myoracle_mcp/server.py` (`FastMCP`). A new
Python file is not finished until that server can run it.

## Workflow

1. **Create the module** under `oracle_single/myoracle_mcp/` (for example
   `alert_log.py`). The module holds the logic; it must not open saved
   connections itself.
2. **Register the tool** in `server.py`: import the module and add one
   `@mcp.tool()` function per user-facing action. The tool validates arguments
   and delegates to the module. Do not copy the module body into `server.py`.

   ```python
   # myoracle_mcp/server.py
   @mcp.tool()
   def run_example(connection_name: str) -> dict:
       """Run the example check on one saved Oracle target."""
       return example_module.run(connection_name)
   ```

3. **Document the tool** in `oracle_single/myoracle_mcp/README.md` using the
   same name and behavior.
4. **Test it**: add or extend a test in `oracle_single/myoracle_mcp/test_server.py`
   when the behavior can be checked without a live database.
5. **Finish the original task by calling the new tool.** Do not run the logic
   from a one-off script in `ORCL/`, a temp path, `sqlplus`, or a private
   import of `server.py`.

## Rules of thumb

- One `@mcp.tool()` per user-facing action; tools validate inputs before
  connecting or changing Oracle state.
- If an existing tool already does the job, call it instead of adding a new one
  (the RH connection check is the `check_saved_oracle_connectivity` tool).
- Never create or run `myoracle_mcp/a.py`; a project hook blocks it.