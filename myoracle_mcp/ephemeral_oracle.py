"""Ephemeral Oracle connectivity check reusing one saved connection template.

Copies every saved detail from a base connection (user, privilege mode,
service/SID, credentials) and only overrides the host, with an optional
port override. Nothing is persisted to ``connections.json``.
"""

from __future__ import annotations

import ipaddress
import re
import time
from typing import Any, Callable


_HOST_LABEL = r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
_HOSTNAME_RE = re.compile(rf"^{_HOST_LABEL}(\.{_HOST_LABEL})*\.?$")


def _validate_host(host: str) -> str:
    safe_host = str(host or "").strip()
    if not safe_host:
        raise ValueError("host must not be empty.")
    try:
        ipaddress.ip_address(safe_host)
        return safe_host
    except ValueError:
        pass
    if len(safe_host) > 253 or not _HOSTNAME_RE.fullmatch(safe_host):
        raise ValueError("host must be a valid IPv4/IPv6 address or hostname.")
    return safe_host


def _validate_port(port: Any) -> int | None:
    if port is None:
        return None
    try:
        safe_port = int(port)
    except (TypeError, ValueError) as exc:
        raise ValueError("port must be an integer between 1 and 65535.") from exc
    if not 1 <= safe_port <= 65535:
        raise ValueError("port must be an integer between 1 and 65535.")
    return safe_port


def effective_connection(
    base_connection_name: str,
    base_connection: dict[str, Any],
    host: str | None,
    port: int | None,
    require_host: bool = True,
) -> dict[str, Any]:
    """Return a copy of the saved record with the host and port overrides."""
    if not str(base_connection_name or "").strip():
        raise ValueError("base_connection_name must not be empty.")
    if not isinstance(base_connection, dict):
        raise ValueError("base_connection must be a saved connection record.")
    safe_host = _validate_host(host) if str(host or "").strip() else None
    if require_host and safe_host is None:
        raise ValueError("host must not be empty.")
    safe_port = _validate_port(port)

    effective = dict(base_connection)
    if safe_host is not None:
        effective["host"] = safe_host
    if safe_port is not None:
        effective["port"] = safe_port
    effective["connection_name"] = str(base_connection.get("connection_name") or base_connection_name)
    return effective


def check_host(
    base_connection_name: str,
    base_connection: dict[str, Any],
    host: str,
    port: int | None,
    connect: Callable[[dict[str, Any]], Any],
) -> dict[str, Any]:
    """Open and close one Oracle connection with an overridden host.

    ``base_connection`` is the already-read saved record for
    ``base_connection_name``. ``connect`` opens a connection from an
    effective connection dict and must return a closeable object.
    """
    effective = effective_connection(base_connection_name, base_connection, host, port)

    started = time.monotonic()
    connection = connect(effective)
    try:
        close = getattr(connection, "close", None)
        if callable(close):
            close()
    finally:
        pass
    elapsed_ms = int((time.monotonic() - started) * 1000)
    sid = str(effective.get("sid") or effective.get("database"))
    return {
        "base_connection_name": str(base_connection_name),
        "host": str(effective["host"]),
        "port": int(effective["port"]),
        "sid": sid,
        "status": "connected",
        "elapsed_ms": elapsed_ms,
    }


LAST_SCN_SQL = """
    select to_char(scn_to_timestamp(current_scn), 'YYYY-MM-DD HH24:MI:SS'),
           to_char(sysdate, 'YYYY-MM-DD HH24:MI:SS'),
           current_scn
      from v$database
"""


def last_scn_date(
    base_connection_name: str,
    base_connection: dict[str, Any],
    host: str | None,
    port: int | None,
    connect: Callable[[dict[str, Any]], Any],
) -> dict[str, Any]:
    """Return the current SCN and the timestamp Oracle maps it to.

    The saved host is used unless ``host`` (and optionally ``port``) is
    overridden. The connection is opened read-only and closed afterwards.
    """
    effective = effective_connection(
        base_connection_name, base_connection, host, port, require_host=False
    )
    connection = connect(effective)
    try:
        with connection.cursor() as cursor:
            cursor.execute(LAST_SCN_SQL)
            scn_timestamp, database_time, current_scn = cursor.fetchone()
    finally:
        close = getattr(connection, "close", None)
        if callable(close):
            close()
    sid = str(effective.get("sid") or effective.get("database"))
    return {
        "base_connection_name": str(base_connection_name),
        "host": str(effective["host"]),
        "port": int(effective["port"]),
        "sid": sid,
        "current_scn": int(current_scn),
        "scn_timestamp": str(scn_timestamp),
        "database_time": str(database_time),
    }
