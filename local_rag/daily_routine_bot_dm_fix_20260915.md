# Daily routine bot DM fix - 2026-09-15

- Request and scope: make the repository daily Oracle routine send a default direct message and verify the message in Slack.
- Configuration: added tracked `myoracle_mcp/config.yaml`, using JSON-compatible YAML, with `daily_routine.slack_user_id`. The prior Windows user-environment default was removed.
- Code change: when no explicit `slack_channel_id` is supplied, `daily_rutione_check` uses the configured Slack user ID, calls Slack `conversations.open` with the existing `MCP/Slack` bot token, and sends to the bot-owned DM. An explicit channel ID still overrides the default.
- Verification: compilation and 12 unit tests passed. After reloading through Super-MCP, the live routine reported Slack delivery success to bot DM `D0C2VEPHPTJ` at timestamp `1789494933.170109`. The Slack plugin read that conversation and confirmed the exact routine summary message is present.
- Outcome: commit `ad3cb69` was pushed to `main`. No Oracle, backup, or Scheduler state was modified.
