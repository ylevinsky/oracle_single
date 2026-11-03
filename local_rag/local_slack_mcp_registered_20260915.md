# Local Slack MCP registered - 2026-09-15

- Scope: Replace the direct hosted Slack MCP registration with the installed local Slack stdio server.
- Codex registration: `super-mcp` is the sole configured Codex MCP entry and starts `super-mcp-router.cmd`.
- Router registration: the `slack` package invokes a local launcher, which starts the local `mcp-server-slack.cmd` executable.
- Validation: the Super-MCP JSON configuration parsed successfully and Codex reported `super-mcp` as enabled.
- Authentication state: the launcher obtains the Slack bot token and workspace ID from the Windows Credential Manager generic credential target `MCP/Slack`. Store the workspace ID as the credential username and the bot token as the credential password. The credential was absent during this check, so no Slack API call was attempted.
- Credential setup: `C:\Users\brillix\.super-mcp\set-slack-mcp-credential.ps1` prompts interactively for those two values, writes the generic credential through the Windows Credential Manager API, and clears the temporary secret buffer. It does not print or persist the token in a file or command line.
- Security: no credential values were written to configuration, source control, this report, or the RAG index.
