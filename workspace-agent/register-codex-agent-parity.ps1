# Register Codex / VS Code parity with Cursor agent assets
#
# Run from an elevated or normal PowerShell session:
#   pwsh -File C:\git\scripts\register-codex-agent-parity.ps1
#
# Requires: codex CLI on PATH, Node for hooks

$ErrorActionPreference = 'Stop'
$GitRoot = 'C:\git'
$CursorPlugins = 'C:\Users\brillix\.cursor\plugins\cache\cursor-public'

function Ensure-Junction {
    param(
        [string]$Link,
        [string]$Target
    )
    $parent = Split-Path -Parent $Link
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    if (Test-Path -LiteralPath $Link) { return }
    New-Item -ItemType Junction -Path $Link -Target $Target | Out-Null
    Write-Host "Junction: $Link -> $Target"
}

# Codex skills marketplace: junctions to Cursor project skills (single source of truth)
$skillNames = @('add-myoracle-tool', 'find-myoracle-mcp', 'propose-improvements')
foreach ($name in $skillNames) {
    Ensure-Junction -Link (Join-Path $GitRoot ".github\skills\$name") -Target (Join-Path $GitRoot ".cursor\skills\$name")
}

# Plugin bundle skills (same junctions)
foreach ($name in $skillNames) {
    Ensure-Junction -Link (Join-Path $GitRoot ".github\plugins\git-oracle-agent\skills\$name") -Target (Join-Path $GitRoot ".cursor\skills\$name")
}

# Local git-agent plugin marketplace (.claude-plugin/marketplace.json at repo root)
Write-Host 'Adding git-agent Codex plugin marketplace...'
& codex plugin marketplace add $GitRoot 2>&1 | Write-Host
Write-Host 'Installing git-oracle-agent plugin...'
& codex plugin add git-oracle-agent@git-agent 2>&1 | Write-Host

# Optional: install Mem0 for Codex (same vendor as Cursor mem0 plugin; requires MEM0_API_KEY)
Write-Host 'Installing mem0 Codex plugin from openai curated cache if present...'
$mem0Codex = Join-Path $env:USERPROFILE '.codex\plugins\cache\openai-api-curated\mem0'
if (Test-Path -LiteralPath $mem0Codex) {
    & codex plugin marketplace add $mem0Codex 2>&1 | Write-Host
} else {
    Write-Host 'Mem0 curated cache not found; enable mem0 in Codex plugin UI or run: codex plugin add mem0@openai-api-curated'
}

Write-Host ''
Write-Host 'Done. Restart VS Code / Codex and reload MCP (Developer: Reload Window).'
Write-Host 'Verify Oracle MCP: codex mcp list  (should include super-mcp / myoracle via router)'
