"""Standalone CLI to compare or copy schemas toward Spain without Data Pump.

Run from the repository root::

    python -m myoracle_mcp.schema_movement_process copy --source RH --schema ATE_RESULTS
    python -m myoracle_mcp.schema_movement_process compare --source RH --target Spain
    python -m myoracle_mcp.schema_movement_process deploy-to-spain
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path
from typing import Any, Callable

import schema_sql_copy
import schema_movement_new

MYORACLE_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = MYORACLE_DIR.parent
DEFAULT_SPAIN_REMOTE_DIR = r"C:/ORCL/schema_movement"
PROCESS_BUNDLE = (
    "schema_movement_process.py",
    "schema_movement_new.py",
    "schema_sql_copy.py",
    "schema_datapump.py",
    "schema_movement.py",
)


def _connection_aliases(connection: dict[str, Any]) -> list[str]:
    aliases = [
        str(connection.get("host") or ""),
        str(connection.get("database") or ""),
        str(connection.get("sid") or ""),
    ]
    host = aliases[0]
    if host:
        try:
            aliases.append(socket.gethostbyname(host))
        except OSError:
            pass
    return [alias for alias in aliases if alias]


def parse_remap(values: list[str]) -> dict[str, str]:
    """Parse ``OLD=NEW`` tablespace remap pairs from the command line."""
    remap: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"tablespace remap must be OLD=NEW, got: {item}")
        old, new = item.split("=", 1)
        remap[old.strip()] = new.strip()
    return schema_sql_copy.normalize_remap(remap) if remap else {}


def bundle_paths() -> list[Path]:
    """Return the module files shipped to the Spain host."""
    missing = [name for name in PROCESS_BUNDLE if not (MYORACLE_DIR / name).is_file()]
    if missing:
        raise FileNotFoundError(f"bundle modules missing under myoracle_mcp: {', '.join(missing)}")
    return [MYORACLE_DIR / name for name in PROCESS_BUNDLE]


def deploy_bundle_to_spain(
    *,
    remote_directory: str = DEFAULT_SPAIN_REMOTE_DIR,
    connection_name: str = schema_movement_new.SPAIN_CONNECTION,
    upload: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Upload the Python schema-movement bundle to the Spain Repair Center host."""
    from server import _read_connection, _read_windows_credential, _ssh_settings

    import remote_copy

    connection = _read_connection(connection_name)
    username, target, port = _ssh_settings(connection_name, connection)
    password = _read_windows_credential(target)
    host = str(connection["host"])
    sources = bundle_paths()
    upload_fn = upload or remote_copy.upload_with_scp
    try:
        result = upload_fn(host, port, username, password, sources, remote_directory)
    except RuntimeError as exc:
        if not remote_copy.missing_directory(str(exc)):
            raise
        remote_copy.create_remote_directory(host, port, username, password, remote_directory)
        result = upload_fn(host, port, username, password, sources, remote_directory)
    return {
        "connection_name": connection_name,
        "remote_directory": remote_directory,
        "uploaded": [path.name for path in sources],
        "seconds": result.get("seconds"),
    }


def run_compare(
    source: str,
    target: str,
    connect: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    from server import _connect_saved_oracle, _read_connection

    source_name = schema_movement_new.resolve_connection_name(source)
    target_name = schema_movement_new.resolve_connection_name(target)
    connect = connect or _connect_saved_oracle
    source_meta = _read_connection(source_name)
    target_meta = _read_connection(target_name)

    def inventory(connection_name: str) -> dict[str, Any]:
        database = connect(connection_name)
        try:
            with database.cursor() as cursor:
                return schema_movement_new.collect_inventory(cursor)
        finally:
            database.close()

    source_inventory = inventory(source_name)
    target_inventory = inventory(target_name)
    comparison = schema_movement_new.compare_inventories(
        source_inventory,
        target_inventory,
        _connection_aliases(source_meta),
        _connection_aliases(target_meta),
    )
    return {
        "source_connection": source_name,
        "target_connection": target_name,
        **comparison,
    }


def run_copy(
    source: str,
    schemas: list[str],
    *,
    target: str | None,
    to_spain: bool,
    confirmed: bool,
    resume: bool,
    tablespace_remap: dict[str, str] | None,
    connect: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    from server import _connect_saved_oracle

    connect = connect or _connect_saved_oracle
    if to_spain:
        return schema_movement_new.copy_schemas_to_spain(
            source,
            schemas,
            confirmed=confirmed,
            tablespace_remap=tablespace_remap,
            connect=connect,
            resume=resume,
        )
    if not target:
        raise ValueError("pass --target or use --to-spain")
    return schema_movement_new.copy_schemas(
        schema_movement_new.resolve_connection_name(source),
        schema_movement_new.resolve_connection_name(target),
        schemas,
        confirmed=confirmed,
        tablespace_remap=tablespace_remap,
        connect=connect,
        resume=resume,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare or copy Oracle schemas with Python DBMS_METADATA (no Data Pump)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    compare = sub.add_parser("compare", help="read-only schema movement inventory")
    compare.add_argument("--source", required=True, help="saved source connection name")
    compare.add_argument(
        "--target",
        default="Spain",
        help=f"saved target connection (default Spain / {schema_movement_new.SPAIN_CONNECTION})",
    )

    copy = sub.add_parser("copy", help="copy one or more schemas")
    copy.add_argument("--source", required=True, help="saved source connection name")
    copy.add_argument(
        "--schema",
        dest="schemas",
        action="append",
        required=True,
        help="schema to copy (repeat for multiple)",
    )
    copy.add_argument(
        "--target",
        help=f"saved target connection (default with --to-spain: {schema_movement_new.SPAIN_CONNECTION})",
    )
    copy.add_argument(
        "--to-spain",
        action="store_true",
        help="copy onto the Spain Repair Center with SPAIN_TBS remap",
    )
    copy.add_argument(
        "--remap",
        action="append",
        default=[],
        metavar="OLD=NEW",
        help="extra tablespace remap (merged with Spain defaults when --to-spain)",
    )
    copy.add_argument("--resume", action="store_true", help="create only missing objects/rows")
    copy.add_argument(
        "--confirmed",
        action="store_true",
        help="apply changes (default is plan-only)",
    )

    deploy = sub.add_parser(
        "deploy-to-spain",
        help="upload this Python bundle to the Spain host for on-box runs",
    )
    deploy.add_argument(
        "--remote-directory",
        default=DEFAULT_SPAIN_REMOTE_DIR,
        help="Windows folder on the Spain host",
    )
    return parser


def copy_targets_spain(args: argparse.Namespace) -> bool:
    """Return whether a copy command should use the Spain Repair Center."""
    return bool(args.to_spain or not args.target)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "compare":
            payload = run_compare(args.source, args.target, connect=_connect)
        elif args.command == "copy":
            remap = parse_remap(args.remap) if args.remap else None
            payload = run_copy(
                args.source,
                args.schemas,
                target=args.target,
                to_spain=copy_targets_spain(args),
                confirmed=args.confirmed,
                resume=args.resume,
                tablespace_remap=remap,
                connect=_connect,
            )
        elif args.command == "deploy-to-spain":
            payload = deploy_bundle_to_spain(remote_directory=args.remote_directory)
        else:
            raise ValueError(f"unknown command: {args.command}")
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("status") not in {"error"} else 1


_connect: Callable[[str], Any] | None = None


def _set_connect(connect: Callable[[str], Any] | None) -> None:
    global _connect
    _connect = connect


if __name__ == "__main__":
    raise SystemExit(main())
