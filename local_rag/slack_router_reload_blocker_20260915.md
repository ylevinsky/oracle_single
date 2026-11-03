# Slack router reload blocker - 2026-09-15

- User request and scope: Connect the current Codex session to Slack through the repository Super-MCP router.
- Connection record check: `C:\\git\\ORCL\\connectios_history.md` has no Slack workspace connection record or approved credential reference.
- Configured state: `C:\\Users\\brillix\\.super-mcp\\config.json` defines Slack as a local stdio server through `slack-mcp-launcher.ps1`, which is designed to retrieve its Slack credential from Windows Credential Manager.
- Live state: Super-MCP health reports the active `slack` package is instead an HTTP package at `https://mcp.slack.com/mcp`.
- Exact rejection: `missing_token`.
- Verified blocker: The running Super-MCP parent has not reloaded its configuration from disk. Package restart refreshes only its in-memory startup configuration, so it cannot activate the local Slack launcher.
- Required next action: Reload/restart the Codex session (and therefore its Super-MCP parent), then run the Slack package health check and authentication flow.
- Security: No Slack credentials, token values, workspace data, or message content were accessed or stored.
