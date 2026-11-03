# Slack essence notification blocker - 2026-09-15

- Request and scope: send the daily Oracle routine summary to Slack channel name `essence` through Super-MCP.
- Channel information: the daily routine requires a Slack channel ID in `slack_channel_id`; a channel name cannot be supplied to that argument without first resolving it.
- Verified blocker: Super-MCP package `slack` is in error state. Its stdio connection closes during startup; diagnostics reported no observed child spawn, child close observed, and no stderr captured. The package cannot currently list channels or send a message.
- Outcome: no Slack message was sent and no Oracle operation was rerun. The RAG database health was already verified through `myoracle`; this record awaits routed indexing.
