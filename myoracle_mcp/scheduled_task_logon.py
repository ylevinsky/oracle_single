"""Change a remote Windows scheduled task to run with nobody logged on."""

from __future__ import annotations

import base64
import json
import re
from typing import Any


_TASK_NAME = re.compile(r"\\[A-Za-z0-9_. ()-]+(?:\\[A-Za-z0-9_. ()-]+)*")


def split_task_name(task_name: str) -> tuple[str, str]:
    """Return the Task Scheduler folder and leaf name for an absolute task path."""
    if not _TASK_NAME.fullmatch(task_name):
        raise ValueError("task_name must be an absolute Windows Task Scheduler path")
    folder, _separator, leaf = task_name.rpartition("\\")
    return folder + "\\", leaf


def set_run_whether_logged_on(client: Any, task_name: str, password: str) -> dict[str, str]:
    """Set one task to run whether its existing account is logged on.

    ``password`` is written to the remote PowerShell process on stdin. It is not
    placed in the SSH command and is removed from any returned text.
    """
    if not password:
        raise ValueError("password must not be empty")
    task_path, task_leaf = split_task_name(task_name)
    script = f"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$raw = [Console]::In.ReadToEnd()
if ($raw.Length -gt 0 -and $raw[-1] -eq "`n") {{ $raw = $raw.Substring(0, $raw.Length - 1) }}
if ($raw.Length -gt 0 -and $raw[-1] -eq "`r") {{ $raw = $raw.Substring(0, $raw.Length - 1) }}
if (-not $raw) {{ throw 'password was empty' }}
$task = Get-ScheduledTask -TaskPath '{task_path}' -TaskName '{task_leaf}'
$principal = [string]$task.Principal.UserId
$account = $principal
if ($principal -like 'S-1-*') {{
  $account = (New-Object System.Security.Principal.SecurityIdentifier($principal)).Translate([System.Security.Principal.NTAccount]).Value
}}
Set-ScheduledTask -TaskPath '{task_path}' -TaskName '{task_leaf}' -User $account -Password $raw | Out-Null
$updated = Get-ScheduledTask -TaskPath '{task_path}' -TaskName '{task_leaf}'
$logon = [string]$updated.Principal.LogonType
if ($logon -ne 'Password') {{ throw "logon type is $logon" }}
@{{ task = ($updated.TaskPath + $updated.TaskName); user = $account; logon_type = $logon }} | ConvertTo-Json -Compress
"""
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    command = f"powershell.exe -NoProfile -NonInteractive -EncodedCommand {encoded}"
    stdin, stdout, stderr = client.exec_command(command, timeout=60, get_pty=False)
    stdin.write(password + "\n")
    stdin.flush()
    stdin.channel.shutdown_write()
    exit_status = int(stdout.channel.recv_exit_status())
    output = _redact(stdout.read().decode("utf-8", errors="replace"), password)
    error = _redact(stderr.read().decode("utf-8", errors="replace"), password)
    if exit_status != 0:
        detail = " ".join((error or output).split())
        raise RuntimeError(detail or f"scheduled task update exited {exit_status}")
    payload = _json_object(output)
    if payload.get("logon_type") != "Password":
        raise RuntimeError("scheduled task did not switch to a stored-password logon")
    return {
        "task": str(payload.get("task") or task_name),
        "user": str(payload.get("user") or ""),
        "logon_type": "Password",
    }


def _redact(text: str, password: str) -> str:
    return text.replace(password, "***")


def _json_object(text: str) -> dict[str, Any]:
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed
    raise RuntimeError("scheduled task update did not return a status object")
