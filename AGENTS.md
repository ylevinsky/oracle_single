# Repository operating rules

## Database connections

Before every database connection request:

1. Read `.db/connections.json`.
2. If the connection is missing or incorrect, update or create its complete record in `.db/connections.json`, including credentials.
3. The repository owner explicitly requires complete connection information, including unsafe credentials, to be stored in the local Git repository.

## Temporary scripts

1. All requests must prioritize implementation through this repository's MCP server. Prefer adding or using an MCP tool over one-off commands or standalone scripts.
2. When a temporary script is necessary for development or validation, create it inside `temp_scripts/` only. After successful execution, promote it into the MCP server as an appropriate tested tool before deleting it, unless the user asks to retain it.
3. Register promoted tools with `@mcp.tool()` and document them in the MCP README when applicable.

## Local RAG synchronization

After every finding, diagnosis, handled error, or software/repository change, update the local RAG database by ingesting the relevant changed or newly created supported source file(s). Preserve sanitized content and never index credentials, secrets, or other sensitive values.
