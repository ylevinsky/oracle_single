"""Read-only MIN/MAX timestamp ranges for non-Oracle-maintained tables.

For every table owned by a non-Oracle-maintained schema that has at least one
``DATE`` or ``TIMESTAMP`` column, this module computes the overall latest and
earliest timestamp value across those columns and reports the tables ordered
by segment size, largest first. Values are read with one aggregate query per
table; nothing is written.

Tables whose name contains ``$`` are never queried and never reported. This
covers materialized view logs (``MLOG$_...``, ``RUPD$_...``) and every other
Oracle internal-style name; they are maintenance artifacts rather than user
data.
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime
from typing import Any, Callable

import ephemeral_oracle

COLUMN_SQL = """
    select c.owner, c.table_name, c.column_name, c.data_type, c.column_id
      from dba_tab_columns c
      join dba_tables t
        on t.owner = c.owner and t.table_name = c.table_name
      join dba_users u
        on u.username = c.owner
     where u.oracle_maintained = 'N'
       and t.temporary = 'N'
       and nvl(t.external, 'NO') = 'NO'
       and instr(c.table_name, '$') = 0
       and (c.data_type = 'DATE' or c.data_type like 'TIMESTAMP%')
     order by c.owner, c.table_name, c.column_id
"""

SIZE_SQL = """
    select owner, segment_name, sum(bytes)
      from dba_segments
     where segment_type = 'TABLE'
       and owner in (select username from dba_users where oracle_maintained = 'N')
     group by owner, segment_name
"""

_IDENTIFIER_RE = re.compile(r"[A-Za-z][A-Za-z0-9_$#]{0,127}")
PER_TABLE_CALL_TIMEOUT_MS = 120_000


def is_excluded_table_name(table_name: Any) -> bool:
    """True for names that must never be queried or reported.

    Any ``$`` in the table name excludes it: materialized view logs
    (``MLOG$_...``, ``RUPD$_...``) and every other Oracle internal-style
    name.
    """
    return "$" in str(table_name or "")


def _quote_identifier(name: Any) -> str:
    text = str(name)
    if not _IDENTIFIER_RE.fullmatch(text):
        raise ValueError(f"Unsafe Oracle identifier: {text[:64]!r}")
    return f'"{text}"'


def _table_query(owner: str, table: str, columns: list[str]) -> str:
    selects = []
    for column in columns:
        safe_column = _quote_identifier(column)
        selects.append(f"max({safe_column})")
        selects.append(f"min({safe_column})")
    target = f"{_quote_identifier(owner)}.{_quote_identifier(table)}"
    return f"select {', '.join(selects)} from {target}"


def _format_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _overall_range(row: tuple) -> tuple[str | None, str | None]:
    """Return the overall latest and earliest value across all columns.

    Values are compared per column (same type) and the per-column extremes
    are compared as formatted strings, so naive and timezone-aware columns
    never meet in one Python comparison.
    """
    column_maxima: list[str] = []
    column_minima: list[str] = []
    for index in range(0, len(row), 2):
        column_max = row[index]
        column_min = row[index + 1] if index + 1 < len(row) else None
        formatted_max = _format_value(column_max)
        formatted_min = _format_value(column_min)
        if formatted_max is not None:
            column_maxima.append(formatted_max)
        if formatted_min is not None:
            column_minima.append(formatted_min)
    if not column_maxima:
        return None, None
    return max(column_maxima), min(column_minima)


def list_timestamp_ranges(
    connection_name: str,
    connection: dict[str, Any],
    host: str | None,
    port: int | None,
    connect: Callable[[dict[str, Any]], Any],
    max_tables: int | None = None,
) -> dict[str, Any]:
    """List DATE/TIMESTAMP min/max per non-Oracle-maintained table by size.

    ``connection`` is the already-read saved record for ``connection_name``;
    ``host`` and ``port`` optionally override its endpoint without persisting
    anything. Tables are ordered by segment size, largest first.
    """
    if max_tables is not None and (
        isinstance(max_tables, bool) or not isinstance(max_tables, int) or max_tables < 1
    ):
        raise ValueError("max_tables must be a positive integer when provided.")
    effective = ephemeral_oracle.effective_connection(
        connection_name, connection, host, port, require_host=False
    )
    started = time.monotonic()
    database = connect(effective)
    try:
        with database.cursor() as cursor:
            cursor.execute(COLUMN_SQL)
            columns_by_table: dict[tuple[str, str], list[tuple[str, str]]] = {}
            excluded_tables: set[tuple[str, str]] = set()
            for owner, table, column, data_type, _column_id in cursor:
                key = (str(owner), str(table))
                if is_excluded_table_name(table):
                    excluded_tables.add(key)
                    continue
                columns_by_table.setdefault(key, []).append((str(column), str(data_type)))
            cursor.execute(SIZE_SQL)
            sizes = {
                (str(owner), str(name)): int(byte_count or 0)
                for owner, name, byte_count in cursor
                if not is_excluded_table_name(name)
            }

        tables = sorted(columns_by_table, key=lambda key: (-(sizes.get(key, 0)), key))
        if max_tables is not None:
            tables = tables[:max_tables]

        results = []
        with database.cursor() as cursor:
            cursor.call_timeout = PER_TABLE_CALL_TIMEOUT_MS
            for owner, table in tables:
                columns = columns_by_table[(owner, table)]
                entry: dict[str, Any] = {
                    "owner": owner,
                    "table_name": table,
                    "size_mb": round(sizes.get((owner, table), 0) / (1024 * 1024), 1),
                    "columns": [name for name, _data_type in columns],
                }
                try:
                    cursor.execute(_table_query(owner, table, [name for name, _ in columns]))
                    max_timestamp, min_timestamp = _overall_range(cursor.fetchone() or ())
                    entry["max_timestamp"] = max_timestamp
                    entry["min_timestamp"] = min_timestamp
                    if max_timestamp is None:
                        entry["note"] = "no rows or every timestamp value is null"
                except Exception as exc:
                    entry["error"] = str(exc).splitlines()[0][:300]
                results.append(entry)

        return {
            "connection_name": str(effective.get("connection_name") or connection_name),
            "host": str(effective["host"]),
            "port": int(effective["port"]),
            "tables_with_timestamp_columns": len(columns_by_table),
            "tables_excluded_dollar_or_mv_log": len(excluded_tables),
            "tables_reported": len(results),
            "elapsed_seconds": round(time.monotonic() - started, 1),
            "tables": results,
        }
    finally:
        close = getattr(database, "close", None)
        if callable(close):
            close()