"""Read-only ad-hoc SQL query against a saved Oracle connection.

Runs one SELECT (or WITH ... SELECT) statement per call. The statement is
validated before connecting so that DML, DDL, transaction control, and
session changes are rejected up front. Nothing is persisted anywhere.
"""

from __future__ import annotations

import re
from typing import Any, Callable

_FORBIDDEN_PATTERN = re.compile(
    r"\b(for\s+update\s*(?:of|nowait|wait|skip\s+locked)?)\b"
    r"|\b(grant|revoke|analyze|audit|comment|flashback|purge|rename)\b"
    r"|\b(merge|upsert)\b"
    r"|\b(dbms_\w+|utl_\w+)\.\w+",
    re.IGNORECASE,
)

_ALLOWED_FIRST_WORD = re.compile(r"^(select|with)\b", re.IGNORECASE)


def _validate_query(sql: str) -> str:
    statement = str(sql or "").strip()
    if not statement:
        raise ValueError("sql must not be empty.")
    statement = statement.rstrip(";").rstrip()
    if not _ALLOWED_FIRST_WORD.match(statement):
        raise ValueError("sql must start with SELECT or WITH (read-only queries only).")
    if ";" in statement:
        raise ValueError("sql must contain a single statement (no semicolons).")
    match = _FORBIDDEN_PATTERN.search(statement)
    if match:
        raise ValueError(f"sql contains a forbidden construct: {match.group(0)!r}")
    return statement


def _validate_max_rows(max_rows: Any) -> int:
    try:
        safe_rows = int(max_rows)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_rows must be an integer between 1 and 5000.") from exc
    if not 1 <= safe_rows <= 5000:
        raise ValueError("max_rows must be an integer between 1 and 5000.")
    return safe_rows


def _validate_host(host: Any) -> str | None:
    if not str(host or "").strip():
        return None
    safe_host = str(host).strip()
    if len(safe_host) > 253 or not re.fullmatch(
        r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*\.?", safe_host
    ):
        if not re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", safe_host):
            raise ValueError("host must be a valid IPv4 address or hostname.")
    return safe_host


def run_saved_query(
    base_connection_name: str,
    base_connection: dict[str, Any],
    sql: str,
    max_rows: Any,
    connect: Callable[[dict[str, Any]], Any],
    host: str | None = None,
    port: Any = None,
    service_name: str | None = None,
    sid: str | None = None,
) -> dict[str, Any]:
    """Run one read-only statement on a saved Oracle target and return its rows.

    ``base_connection`` is the already-read saved record for
    ``base_connection_name``. ``connect`` opens a connection from the
    effective connection dict and must return a closeable object. Optional
    ``host``/``port``/``service_name``/``sid`` overrides are applied to the
    copy only and never persisted. An empty ``service_name`` connects by SID.
    """
    statement = _validate_query(sql)
    safe_rows = _validate_max_rows(max_rows)
    if not str(base_connection_name or "").strip():
        raise ValueError("connection_name must not be empty.")
    if not isinstance(base_connection, dict):
        raise ValueError("connection must be a saved connection record.")

    effective = dict(base_connection)
    safe_host = _validate_host(host)
    if safe_host is not None:
        effective["host"] = safe_host
    if port is not None:
        try:
            safe_port = int(port)
        except (TypeError, ValueError) as exc:
            raise ValueError("port must be an integer between 1 and 65535.") from exc
        if not 1 <= safe_port <= 65535:
            raise ValueError("port must be an integer between 1 and 65535.")
        effective["port"] = safe_port
    if service_name is not None:
        if str(service_name).strip():
            effective["service_name"] = str(service_name).strip()
        else:
            effective.pop("service_name", None)
    if sid is not None:
        if str(sid).strip():
            effective["sid"] = str(sid).strip()
        else:
            effective.pop("sid", None)
    effective["connection_name"] = str(
        base_connection.get("connection_name") or base_connection_name
    )

    connection = connect(effective)
    try:
        with connection.cursor() as cursor:
            cursor.execute(statement)
            description = cursor.description
            if description is None:
                raise ValueError("sql did not return a result set; only SELECT is supported.")
            columns = [column[0].lower() for column in description]
            rows = cursor.fetchmany(safe_rows + 1)
            truncated = len(rows) > safe_rows
            rows = rows[:safe_rows]
    finally:
        close = getattr(connection, "close", None)
        if callable(close):
            close()

    def _value(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if hasattr(value, "isoformat"):
            return value.isoformat(sep=" ")
        return str(value)

    sid = str(effective.get("sid") or effective.get("database"))
    return {
        "connection_name": str(base_connection_name),
        "host": str(effective["host"]),
        "port": int(effective["port"]),
        "sid": sid,
        "sql": " ".join(statement.split()),
        "columns": columns,
        "row_count": len(rows),
        "truncated": truncated,
        "max_rows": safe_rows,
        "rows": [[_value(value) for value in row] for row in rows],
    }