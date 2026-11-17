#Requires -Version 5.1
<#
.SYNOPSIS
  Add the next OpenAI API key from Credential Manager to the Hermes openai-api pool.

.PARAMETER CredentialTarget
  Generic credential target (default Hermes/OpenAI/PoolNext).

.PARAMETER HermesCommand
  Hermes CLI on PATH (default hermes).
#>
[CmdletBinding()]
param(
    [string] $CredentialTarget = 'Hermes/OpenAI/PoolNext',
    [string] $HermesCommand = 'hermes'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $scriptDir 'hermes-credential-manager.ps1')

if ($env:OS -ne 'Windows_NT') {
    throw 'This script expects Windows Credential Manager. On Linux, run: hermes auth add openai-api --type api-key'
}

if (-not (Get-Command $HermesCommand -ErrorAction SilentlyContinue)) {
    throw "Hermes CLI '$HermesCommand' was not found on PATH."
}

try {
    $read = [HermesCred.Manager]::Read($CredentialTarget)
    $apiKey = $read.Secret
}
catch [System.ComponentModel.Win32Exception] {
  throw "Credential '$CredentialTarget' was not found. Run set-hermes-openai-pool-credential.ps1 first."
}

if ([string]::IsNullOrWhiteSpace($apiKey)) {
    throw "Credential '$CredentialTarget' has an empty secret."
}
if ($apiKey -notmatch '^(sk-|sk-proj-)') {
    throw 'Stored secret does not look like an OpenAI API key.'
}

try {
    & $HermesCommand auth add openai-api --type api-key --api-key $apiKey
    & $HermesCommand auth list openai-api
}
finally {
    $apiKey = $null
}
