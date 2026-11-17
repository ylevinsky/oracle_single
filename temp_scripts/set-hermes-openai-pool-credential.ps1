#Requires -Version 5.1
<#
.SYNOPSIS
  Store the next OpenAI API key for Hermes in Windows Credential Manager.

.DESCRIPTION
  Target: Hermes/OpenAI/PoolNext (override with -CredentialTarget). Username field
  stores an optional pool label. Run add-hermes-openai-pool-key.ps1 to register
  the key with Hermes.
#>
[CmdletBinding()]
param(
    [string] $CredentialTarget = 'Hermes/OpenAI/PoolNext',
    [string] $Label = 'pool-next'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $scriptDir 'hermes-credential-manager.ps1')

function Convert-SecureStringToPlainText {
    param([Security.SecureString] $Secure)
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

if ($env:OS -ne 'Windows_NT') {
    throw 'Windows Credential Manager is only available on Windows.'
}

$secureKey = Read-Host 'OpenAI API key (sk- or sk-proj-)' -AsSecureString
$plain = Convert-SecureStringToPlainText -Secure $secureKey
try {
    if ($plain -notmatch '^(sk-|sk-proj-)') {
        throw 'Key does not look like an OpenAI API key.'
    }
    [HermesCred.Manager]::Write($CredentialTarget, $Label, $plain)
    Write-Host "Stored '$CredentialTarget' (label '$Label'). Next: .\add-hermes-openai-pool-key.ps1"
}
finally {
    $plain = $null
}
