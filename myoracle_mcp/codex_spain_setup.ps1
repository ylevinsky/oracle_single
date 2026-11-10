# Install Codex CLI on Spain, configure API key, remove Cursor IDE — no machine or Oracle restarts.
param(
    [Parameter(Mandatory = $true)]
    [string]$KeyFile,
    [string]$RepoCodexConfig = 'C:\git\oracle_single\.codex\config.toml',
    [string]$CodexHome = '',
    [switch]$SkipParityScript
)

$ErrorActionPreference = 'Stop'

function Stop-CursorProcesses {
    Get-Process -Name 'Cursor' -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
}

function Remove-CursorInstall {
    Stop-CursorProcesses
    $ids = @('Anysphere.Cursor', 'Cursor.Cursor')
    foreach ($id in $ids) {
        try {
            & winget uninstall --id $id --silent --accept-source-agreements --disable-interactivity 2>$null | Out-Null
        } catch {
            Write-Host "winget uninstall $id skipped: $($_.Exception.Message)"
        }
    }
    $paths = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\cursor'),
        (Join-Path $env:LOCALAPPDATA 'cursor-updater')
    )
    foreach ($path in $paths) {
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
            Write-Host "Removed $path"
        }
    }
}

function Install-CodexCli {
    $env:CODEX_NON_INTERACTIVE = '1'
    if (Get-Command codex -ErrorAction SilentlyContinue) {
        Write-Host 'Codex already on PATH'
        return
    }
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        & npm install -g @openai/codex 2>&1 | Write-Host
        if (Get-Command codex -ErrorAction SilentlyContinue) {
            return
        }
    }
    $script = Invoke-RestMethod -Uri 'https://chatgpt.com/codex/install.ps1' -UseBasicParsing
    Invoke-Expression $script
}

function Configure-Codex {
    param([string]$ApiKey, [string]$Home)
    if (-not $Home) {
        $Home = Join-Path $env:USERPROFILE '.codex'
    }
    if (-not (Test-Path -LiteralPath $Home)) {
        New-Item -ItemType Directory -Path $Home -Force | Out-Null
    }
    [Environment]::SetEnvironmentVariable('CODEX_API_KEY', $ApiKey, 'User')
    $env:CODEX_API_KEY = $ApiKey
    if (Test-Path -LiteralPath $RepoCodexConfig) {
        Copy-Item -LiteralPath $RepoCodexConfig -Destination (Join-Path $Home 'config.toml') -Force
        Write-Host "Copied config from $RepoCodexConfig"
    }
    $version = ''
    if (Get-Command codex -ErrorAction SilentlyContinue) {
        $version = (& codex --version 2>&1 | Out-String).Trim()
    }
    return @{
        codex_home = $Home
        codex_version = $version
    }
}

if (-not (Test-Path -LiteralPath $KeyFile)) {
    throw "Key file missing: $KeyFile"
}
$key = (Get-Content -LiteralPath $KeyFile -Raw).Trim()
if (-not $key) {
    throw 'Key file is empty'
}
Remove-Item -LiteralPath $KeyFile -Force

Remove-CursorInstall
Install-CodexCli
$info = Configure-Codex -ApiKey $key -Home $CodexHome

if (-not $SkipParityScript) {
    $parity = 'C:\git\workspace-agent\register-codex-agent-parity.ps1'
    if (-not (Test-Path -LiteralPath $parity)) {
        $parity = 'C:\git\oracle_single\workspace-agent\register-codex-agent-parity.ps1'
    }
    if (Test-Path -LiteralPath $parity) {
        Write-Host "Running $parity"
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $parity
    }
}

Write-Host 'CODEX_SPAIN_SETUP_OK'
Write-Host ($info | ConvertTo-Json -Compress)
