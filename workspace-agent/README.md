# Workspace agent parity (Cursor + Codex VS Code)

Templates and scripts for the **`C:\git`** workspace root (sibling repos: `oracle_single`, `ORCL`, etc.).

Copy or merge into `C:\git` (see `register-codex-agent-parity.ps1`). The canonical live copy for this monorepo layout is also committed at **`C:\git`** repo `yuri-levinsky/git-workspace` on Origin when pushed.

- `.cursor/` — rules, skills, hooks, MCP
- `.github/` — Codex plugin `git-oracle-agent`, skill junctions
- `.vscode/mcp.json`, `.mcp.json` — VS Code MCP (`myoracle` + `super-mcp`)
- `.codex-config.toml.example` — merge into `C:\git\.codex\config.toml`
- `.claude-plugin-marketplace.json` → `C:\git\.claude-plugin\marketplace.json`

Repository-local Codex MCP overrides: `../.codex/config.toml` (this repo).
