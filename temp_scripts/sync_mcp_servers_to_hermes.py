#!/usr/bin/env python3
"""Merge Cursor/VS Code MCP JSON into Hermes ~/.hermes/config.yaml (mcp_servers).

Reads ``mcpServers`` (Cursor) or ``servers`` (VS Code) and upserts each entry
as a Hermes stdio MCP server definition. Does not store new secrets.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml


def _load_mcp_document(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a JSON object")
    servers = data.get("mcpServers") or data.get("servers")
    if not isinstance(servers, dict):
        raise ValueError(
            f"{path} must contain 'mcpServers' or 'servers' object"
        )
    return servers


def _to_hermes_entry(name: str, entry: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise ValueError(f"Server '{name}' must be an object")

    url = str(entry.get("url") or "").strip()
    command = str(entry.get("command") or "").strip()

    if url:
        hermes: dict[str, Any] = {"url": url, "enabled": True}
        headers = entry.get("headers")
        if isinstance(headers, dict) and headers:
            hermes["headers"] = dict(headers)
        if entry.get("transport"):
            hermes["transport"] = entry["transport"]
        return hermes

    if not command:
        raise ValueError(
            f"Server '{name}' needs 'command' (stdio) or 'url' (HTTP/SSE)"
        )

    hermes = {
        "command": command,
        "enabled": True,
    }
    args = entry.get("args")
    if isinstance(args, list) and args:
        hermes["args"] = [str(a) for a in args]
    env = entry.get("env")
    if isinstance(env, dict) and env:
        hermes["env"] = {str(k): str(v) for k, v in env.items()}

    timeout = entry.get("tool_timeout_sec") or entry.get("timeout")
    if timeout is not None:
        try:
            hermes["timeout"] = int(timeout)
        except (TypeError, ValueError):
            pass

    connect_timeout = entry.get("startup_timeout_sec") or entry.get(
        "connect_timeout"
    )
    if connect_timeout is not None:
        try:
            hermes["connect_timeout"] = int(connect_timeout)
        except (TypeError, ValueError):
            pass

    return hermes


def _hermes_config_path(home: Path) -> Path:
    return home / "config.yaml"


def _merge_mcp_servers(
    config_path: Path, servers: dict[str, dict[str, Any]]
) -> None:
    if config_path.exists():
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    else:
        config = {}

    if not isinstance(config, dict):
        raise ValueError(f"Config at {config_path} must be a YAML mapping")

    mcp = config.setdefault("mcp_servers", {})
    if not isinstance(mcp, dict):
        mcp = {}
        config["mcp_servers"] = mcp

    for name, entry in servers.items():
        mcp[name] = entry

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def _validate_with_hermes(entries: dict[str, dict[str, Any]]) -> list[str]:
    try:
        from hermes_cli.mcp_security import validate_mcp_server_entry
    except ImportError:
        return []

    issues: list[str] = []
    for name, cfg in entries.items():
        issues.extend(validate_mcp_server_entry(name, cfg))
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync MCP server definitions into Hermes config.yaml"
    )
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Path to .cursor/mcp.json, .mcp.json, or equivalent",
    )
    parser.add_argument(
        "--hermes-home",
        type=Path,
        default=Path.home() / ".hermes",
        help="Hermes profile directory (default: ~/.hermes)",
    )
    parser.add_argument(
        "--only",
        nargs="*",
        help="Optional server names to import (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print merged mcp_servers without writing config.yaml",
    )
    args = parser.parse_args()

    raw = _load_mcp_document(args.source)
    if args.only:
        missing = [name for name in args.only if name not in raw]
        if missing:
            raise SystemExit(f"Unknown server name(s): {', '.join(missing)}")
        raw = {name: raw[name] for name in args.only}

    hermes_entries: dict[str, dict[str, Any]] = {}
    for name, entry in raw.items():
        hermes_entries[name] = _to_hermes_entry(name, entry)

    issues = _validate_with_hermes(hermes_entries)
    if issues:
        for issue in issues:
            print(f"validation: {issue}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(yaml.safe_dump({"mcp_servers": hermes_entries}, sort_keys=False))
        return 0

    config_path = _hermes_config_path(args.hermes_home)
    _merge_mcp_servers(config_path, hermes_entries)
    names = ", ".join(sorted(hermes_entries))
    print(f"Updated {config_path} (mcp_servers: {names})")
    print("Next: hermes mcp list && hermes mcp test <name>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
