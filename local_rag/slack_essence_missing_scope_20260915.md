# Slack essence notification attempt - 2026-09-15

- Request and scope: resolve Slack channel `#essence` and send the current daily Oracle routine summary through Super-MCP.
- Feature added: `myoracle__resolve_slack_channel` resolves a visible name to the channel ID required by `daily_rutione_check(slack_channel_id=...)`. It uses the existing `MCP/Slack` Credential Manager token, does not expose or persist that token, handles pagination, and is documented and unit tested.
- Verification: seven `myoracle_mcp` unit tests and Python compilation passed; the package was restarted and the resolver made a live Slack API call through Super-MCP.
- Exact blocker: Slack rejected the channel lookup with `missing_scope`. The bot token lacks the permission required to list/find the `essence` channel, so its ID could not be resolved and no daily-routine message was sent.
- Required external action: grant the Slack app/bot the appropriate channel-read scope and install or reauthorize it for the workspace; ensure it has permission to post in `#essence`. Then rerun the resolver and routine notification.
