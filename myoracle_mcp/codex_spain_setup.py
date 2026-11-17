"""Install Codex and remove Cursor on the Spain Repair Center host over SSH."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any, Callable

SPAIN_CONNECTION = "es_db2_orclsp_sys"
REMOTE_STAGING = r"C:\ORCL\codex_setup"
SETUP_SCRIPT = Path(__file__).with_name("codex_spain_setup.ps1")


def _redact(text: str, secret: str) -> str:
    if secret and secret in text:
        return text.replace(secret, "***")
    return text


def _powershell_single(path: str) -> str:
    return "'" + path.replace("'", "''") + "'"


def build_remote_command(key_file: str, repo_config: str) -> str:
    """Return one remote cmd.exe line that runs the setup script."""
    script = _powershell_single(str(SETUP_SCRIPT).replace("/", "\\"))
    key = _powershell_single(key_file)
    config = _powershell_single(repo_config)
    inner = (
        f"powershell.exe -NoProfile -ExecutionPolicy Bypass -File {script} "
        f"-KeyFile {key} -RepoCodexConfig {config}"
    )
    return f'cmd /c "{inner}"'


def run_codex_spain_setup(
    codex_api_key: str,
    *,
    connection_name: str = SPAIN_CONNECTION,
    confirmed: bool,
    repo_codex_config: str = r"C:\git\oracle_single\.codex\config.toml",
    open_ssh: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Upload setup assets, configure Codex with the API key, and remove Cursor."""
    key = str(codex_api_key or "").strip()
    if not key:
        raise ValueError("codex_api_key is required")
    if len(key) < 20:
        raise ValueError("codex_api_key is too short")
    plan = {
        "connection_name": connection_name,
        "remote_staging": REMOTE_STAGING,
        "repo_codex_config": repo_codex_config,
        "actions": [
            "stop_cursor_processes",
            "uninstall_cursor",
            "install_codex_non_interactive",
            "set_user_codex_api_key",
            "copy_repo_codex_config",
        ],
        "restarts": "none (no Reboot, no Oracle service restart)",
    }
    if not confirmed:
        return {"status": "not_confirmed", **plan}

    from server import _open_ssh

    if not SETUP_SCRIPT.is_file():
        raise FileNotFoundError(f"Missing setup script: {SETUP_SCRIPT}")

    client = (open_ssh or _open_ssh)(connection_name)
    try:
        sftp = client.open_sftp()
        try:
            client.exec_command(f'if not exist "{REMOTE_STAGING}" mkdir "{REMOTE_STAGING}"', timeout=30)
            script_remote = f"{REMOTE_STAGING}/codex_spain_setup.ps1"
            sftp.put(str(SETUP_SCRIPT), script_remote)
            key_remote = f"{REMOTE_STAGING}/codex_api_key.txt"
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
                handle.write(key)
                local_key = handle.name
            try:
                sftp.put(local_key, key_remote)
            finally:
                Path(local_key).unlink(missing_ok=True)
        finally:
            sftp.close()
        _stdin, stdout, stderr = client.exec_command(
            build_remote_command(key_remote.replace("/", "\\"), repo_codex_config),
            timeout=1800,
        )
        exit_status = stdout.channel.recv_exit_status()
        output = stdout.read().decode("utf-8", errors="replace")
        errors = stderr.read().decode("utf-8", errors="replace")
        combined = _redact((output + "\n" + errors).strip(), key)
        if exit_status != 0:
            raise RuntimeError(f"remote setup exited {exit_status}: {combined[-4000:]}")
        if "CODEX_SPAIN_SETUP_OK" not in output:
            raise RuntimeError(f"remote setup did not report success: {combined[-4000:]}")
        info_line = ""
        for line in output.splitlines():
            if line.strip().startswith("{"):
                info_line = line.strip()
                break
        codex_info: dict[str, Any] = {}
        if info_line:
            try:
                codex_info = json.loads(info_line)
            except json.JSONDecodeError:
                codex_info = {"raw": info_line}
        return {
            "status": "completed",
            **plan,
            "codex": codex_info,
            "output_tail": combined[-2000:],
        }
    finally:
        client.close()


def main() -> int:
    import argparse
    import os
    import sys

    parser = argparse.ArgumentParser(description="Install Codex on Spain and remove Cursor (no restarts).")
    parser.add_argument("--connection", default=SPAIN_CONNECTION)
    parser.add_argument(
        "--from-env",
        action="store_true",
        help="read codex API key from CODEX_API_KEY in the environment",
    )
    parser.add_argument("--confirmed", action="store_true")
    parser.add_argument("--repo-config", default=r"C:\git\oracle_single\.codex\config.toml")
    args = parser.parse_args()
    key = os.environ.get("CODEX_API_KEY", "").strip() if args.from_env else ""
    if not key:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": "Set CODEX_API_KEY or pass --from-env after exporting the key locally",
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2
    try:
        result = run_codex_spain_setup(
            key,
            connection_name=args.connection,
            confirmed=args.confirmed,
            repo_codex_config=args.repo_config,
        )
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({k: v for k, v in result.items() if k != "output_tail"}, indent=2, default=str))
    return 0 if result.get("status") in {"not_confirmed", "completed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
