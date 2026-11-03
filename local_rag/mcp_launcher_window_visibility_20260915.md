# MCP launcher window visibility - 2026-09-15

- User request and scope: Close PowerShell windows opened by the Oracle/Slack MCP launchers and prevent future visible windows.
- Diagnosis: The manually invoked diagnostic launcher processes had already exited. The remaining Super-MCP router process pair (`cmd.exe` and `node.exe`) had `MainWindowHandle` zero and an empty window title, so it was running headlessly and was left running because it provides the active MCP transport.
- Configuration change: Added `-WindowStyle Hidden` to the configured PowerShell arguments for the `myoracle` and `slack` child packages in `C:\Users\brillix\.super-mcp\config.json`.
- Verification: The configuration parsed as JSON and both configured argument lists now include `-WindowStyle Hidden`.
- Handled diagnostic error: An initial status command used an unbraced PowerShell variable immediately before a colon and failed with `Variable reference is not valid. ':' was not followed by a valid variable name character.` It was corrected to use `${name}`; no configuration or process state was changed by the failed command.
- Outcome: No visible child PowerShell window remains. The active router need not be closed; the hidden-window setting applies when child packages start or are restarted.
