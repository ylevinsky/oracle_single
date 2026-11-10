#Requires -Version 5.1
<#
.SYNOPSIS
  Register workspace MCP servers (super-mcp, myoracle) with Hermes Agent.

.DESCRIPTION
  Reads workspace-agent\.mcp.json (or override with -Source) and merges stdio
  definitions into %USERPROFILE%\.hermes\config.yaml. Then lists and optionally
  tests each server with `hermes mcp test`.

.EXAMPLE
  .\register-workspace-mcp-for-hermes.ps1

.EXAMPLE
  .\register-workspace-mcp-for-hermes.ps1 -Test
#>
[CmdletBinding()]
param(
    [string] $Source,
    [switch] $Test,
    [string[]] $Only = @('super-mcp', 'myoracle')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $Source) {
    $Source = Join-Path $repoRoot 'workspace-agent\.mcp.json'
}
if (-not (Test-Path -LiteralPath $Source)) {
    $Source = Join-Path $repoRoot '.cursor\mcp.json'
}

$py = @(
    Join-Path $repoRoot 'local_rag\.venv\Scripts\python.exe'
    Join-Path $repoRoot 'myoracle_mcp\.venv\Scripts\python.exe'
    'python'
) | Where-Object { $_ -eq 'python' -or (Test-Path -LiteralPath $_) } | Select-Object -First 1

$sync = Join-Path $PSScriptRoot 'sync_mcp_servers_to_hermes.py'
$onlyArgs = $Only | ForEach-Object { '--only'; $_ }

& $py $sync --source $Source @onlyArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not (Get-Command hermes -ErrorAction SilentlyContinue)) {
    Write-Warning 'hermes CLI not on PATH; config was written but tests were skipped.'
    exit 0
}

hermes mcp list
if (-not $Test) {
    Write-Host 'Run with -Test to call: hermes mcp test super-mcp / myoracle'
    exit 0
}

foreach ($name in $Only) {
    Write-Host "--- hermes mcp test $name ---"
    hermes mcp test $name
}
