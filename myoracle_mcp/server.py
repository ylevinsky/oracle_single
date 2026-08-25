from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from pathlib import Path
from typing import Any

import oracledb
from mcp.server.fastmcp import FastMCP


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
CONNECTIONS_FILE = REPOSITORY_ROOT / ".db" / "connections.json"
TOKEN_LIFETIME_SECONDS = 10 * 60

mcp = FastMCP(
    "myoracle",
    instructions=(
        "Oracle tools scoped to this repository. Before every database connection, "
        "call prepare_connection, show every returned connection detail (including "
        "the stored password) to the user, and ask whether the details are current. "
        "Only after explicit confirmation may you pass the one-time confirmation "
        "token to a database tool. Never reuse a token."
    ),
)

_pending_confirmations: dict[str, tuple[str, float]] = {}
_token_lock = threading.Lock()


def _read_connection(connection_name: str) -> dict[str, Any]:
    try:
        document = json.loads(CONNECTIONS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Connection file not found: {CONNECTIONS_FILE}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {CONNECTIONS_FILE}: {exc}") from exc

    connections = document.get("connections")
    if not isinstance(connections, dict):
        raise ValueError("connections.json must contain a 'connections' object")

    connection = connections.get(connection_name)
    if not isinstance(connection, dict):
        available = ", ".join(sorted(connections)) or "(none)"
        raise ValueError(
            f"Unknown connection '{connection_name}'. Available: {available}"
        )

    required = (
        "engine",
        "host",
        "port",
        "database",
        "username",
        "sslmode",
        "password",
        "purpose",
    )
    missing = [key for key in required if connection.get(key) in (None, "")]
    if missing:
        raise ValueError(
            f"Connection '{connection_name}' is incomplete; missing: {', '.join(missing)}"
        )
    if str(connection["engine"]).lower() != "oracle":
        raise ValueError(f"Connection '{connection_name}' is not an Oracle connection")
    return connection


def _fingerprint(connection_name: str, connection: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"name": connection_name, "connection": connection},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _purge_expired_tokens(now: float) -> None:
    expired = [
        token
        for token, (_, created_at) in _pending_confirmations.items()
        if now - created_at > TOKEN_LIFETIME_SECONDS
    ]
    for token in expired:
        _pending_confirmations.pop(token, None)


def _consume_confirmation(
    connection_name: str, confirmation_token: str
) -> dict[str, Any]:
    # Re-read immediately before connecting so edits invalidate the confirmation.
    connection = _read_connection(connection_name)
    expected_fingerprint = _fingerprint(connection_name, connection)
    now = time.monotonic()
    with _token_lock:
        _purge_expired_tokens(now)
        pending = _pending_confirmations.pop(confirmation_token, None)
    if pending is None:
        raise ValueError(
            "Invalid, expired, or already-used confirmation token. Call "
            "prepare_connection and obtain fresh user confirmation."
        )
    confirmed_fingerprint, _ = pending
    if not secrets.compare_digest(confirmed_fingerprint, expected_fingerprint):
        raise ValueError(
            "The saved connection changed after it was shown. Call "
            "prepare_connection again and reconfirm the current details."
        )
    return connection


def _connect(connection: dict[str, Any]) -> oracledb.Connection:
    sslmode = str(connection["sslmode"]).lower()
    if sslmode not in {"disable", "require"}:
        raise ValueError("Oracle sslmode must be 'disable' or 'require'")

    params = oracledb.ConnectParams(
        host=str(connection["host"]),
        port=int(connection["port"]),
        sid=str(connection.get("sid") or connection["database"]),
        protocol="tcps" if sslmode == "require" else "tcp",
    )
    mode = None
    privilege_mode = str(connection.get("privilege_mode", "")).upper()
    if privilege_mode == "SYSDBA":
        mode = oracledb.AUTH_MODE_SYSDBA
    elif privilege_mode:
        raise ValueError(f"Unsupported Oracle privilege_mode: {privilege_mode}")

    kwargs: dict[str, Any] = {
        "user": str(connection["username"]),
        "password": str(connection["password"]),
        "params": params,
    }
    if mode is not None:
        kwargs["mode"] = mode
    return oracledb.connect(**kwargs)


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "read"):
        return value.read()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _fetch_dicts(cursor: oracledb.Cursor) -> list[dict[str, Any]]:
    columns = [description[0].lower() for description in cursor.description]
    return [
        {column: _json_value(value) for column, value in zip(columns, row)}
        for row in cursor
    ]


@mcp.tool()
def connections_list() -> list[str]:
    """List saved Oracle connection names without connecting to a database."""
    document = json.loads(CONNECTIONS_FILE.read_text(encoding="utf-8"))
    connections = document.get("connections", {})
    return sorted(
        name
        for name, details in connections.items()
        if isinstance(details, dict)
        and str(details.get("engine", "")).lower() == "oracle"
    )


@mcp.tool()
def prepare_connection(connection_name: str) -> dict[str, Any]:
    """Read and return full connection details plus a one-time confirmation token.

    This does not connect. The caller must show every field, including the password,
    and ask the user to confirm that the details are current. The token is valid for
    ten minutes, for one database connection attempt, and only while the record is
    unchanged.
    """
    connection = _read_connection(connection_name)
    token = secrets.token_urlsafe(32)
    now = time.monotonic()
    with _token_lock:
        _purge_expired_tokens(now)
        _pending_confirmations[token] = (
            _fingerprint(connection_name, connection),
            now,
        )
    return {
        "connection_name": connection_name,
        "details": connection,
        "confirmation_token": token,
        "expires_in_seconds": TOKEN_LIFETIME_SECONDS,
        "next_step": (
            "Show all details to the user and ask if they are current. Only after "
            "explicit confirmation call a database tool with this token."
        ),
    }


@mcp.tool()
def list_schemas(connection_name: str, confirmation_token: str) -> dict[str, Any]:
    """Connect once and list schemas after consuming a confirmed one-time token."""
    connection = _consume_confirmation(connection_name, confirmation_token)
    with _connect(connection) as database:
        with database.cursor() as cursor:
            cursor.execute("select username from dba_users order by username")
            schemas = [str(row[0]) for row in cursor]
    return {
        "connection_name": connection_name,
        "database": connection["database"],
        "schema_count": len(schemas),
        "schemas": schemas,
    }


@mcp.tool()
def list_custom_jobs(
    connection_name: str, confirmation_token: str
) -> dict[str, Any]:
    """List Scheduler and legacy jobs owned by non-Oracle-maintained users.

    The one-time confirmation token is consumed before a single read-only database
    connection is opened. Oracle-maintained owners are excluded using DBA_USERS.
    """
    connection = _consume_confirmation(connection_name, confirmation_token)
    scheduler_sql = """
        select j.owner,
               j.job_name,
               j.job_type,
               j.job_action,
               j.enabled,
               j.state,
               j.repeat_interval,
               to_char(
                   j.last_start_date,
                   'YYYY-MM-DD"T"HH24:MI:SS.FF TZH:TZM'
               ) as last_start_date,
               to_char(
                   j.next_run_date,
                   'YYYY-MM-DD"T"HH24:MI:SS.FF TZH:TZM'
               ) as next_run_date,
               j.failure_count
          from dba_scheduler_jobs j
          join dba_users u on u.username = j.owner
         where u.oracle_maintained = 'N'
         order by j.owner, j.job_name
    """
    legacy_sql = """
        select j.job,
               j.log_user,
               j.priv_user,
               j.schema_user,
               j.what,
               j.broken,
               j.failures,
               j.last_date,
               j.next_date,
               j.interval
          from dba_jobs j
          join dba_users u on u.username = j.schema_user
         where u.oracle_maintained = 'N'
         order by j.schema_user, j.job
    """
    with _connect(connection) as database:
        with database.cursor() as cursor:
            cursor.execute(scheduler_sql)
            scheduler_jobs = _fetch_dicts(cursor)
            cursor.execute(legacy_sql)
            legacy_jobs = _fetch_dicts(cursor)
    return {
        "connection_name": connection_name,
        "database": connection["database"],
        "filter": "DBA_USERS.ORACLE_MAINTAINED = 'N'",
        "scheduler_job_count": len(scheduler_jobs),
        "scheduler_jobs": scheduler_jobs,
        "legacy_job_count": len(legacy_jobs),
        "legacy_jobs": legacy_jobs,
    }


@mcp.tool()
def list_top_full_scan_queries(
    connection_name: str,
    confirmation_token: str,
    limit: int = 10,
) -> dict[str, Any]:
    """Rank custom shared-pool SQL with full table scans by physical reads.

    Custom SQL means the parsing schema has DBA_USERS.ORACLE_MAINTAINED = 'N'.
    Statistics are aggregated across child cursors by SQL ID from V$SQL, and a
    qualifying child plan must contain TABLE ACCESS FULL in V$SQL_PLAN.
    """
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    connection = _consume_confirmation(connection_name, confirmation_token)
    ranking_sql = """
        select sql_id,
               parsing_schema_name,
               physical_reads,
               buffer_gets,
               executions,
               round(physical_reads / nullif(executions, 0), 2)
                   as physical_reads_per_execution,
               elapsed_seconds,
               last_active_time,
               sql_text
          from (
                select s.sql_id,
                       max(s.parsing_schema_name) as parsing_schema_name,
                       sum(s.disk_reads) as physical_reads,
                       sum(s.buffer_gets) as buffer_gets,
                       sum(s.executions) as executions,
                       round(sum(s.elapsed_time) / 1000000, 3)
                           as elapsed_seconds,
                       max(s.last_active_time) as last_active_time,
                       max(s.sql_text) as sql_text
                  from v$sql s
                  join dba_users u
                    on u.username = s.parsing_schema_name
                   and u.oracle_maintained = 'N'
                 where exists (
                           select 1
                             from v$sql_plan p
                            where p.sql_id = s.sql_id
                              and p.child_number = s.child_number
                              and p.plan_hash_value = s.plan_hash_value
                              and p.operation = 'TABLE ACCESS'
                              and p.options = 'FULL'
                       )
                 group by s.sql_id
                 order by physical_reads desc
               )
         where rownum <= :limit
    """
    objects_sql = """
        select distinct p.object_owner, p.object_name
          from v$sql_plan p
         where p.sql_id = :sql_id
           and p.operation = 'TABLE ACCESS'
           and p.options = 'FULL'
           and p.object_name is not null
         order by p.object_owner, p.object_name
    """
    with _connect(connection) as database:
        with database.cursor() as cursor:
            cursor.execute(ranking_sql, limit=limit)
            queries = _fetch_dicts(cursor)
            for query in queries:
                cursor.execute(objects_sql, sql_id=query["sql_id"])
                query["full_scan_objects"] = [
                    ".".join(str(part) for part in row if part is not None)
                    for row in cursor
                ]
    return {
        "connection_name": connection_name,
        "database": connection["database"],
        "source": "V$SQL joined to V$SQL_PLAN",
        "custom_filter": "DBA_USERS.ORACLE_MAINTAINED = 'N'",
        "ranking": "V$SQL.DISK_READS descending",
        "query_count": len(queries),
        "queries": queries,
    }


@mcp.tool()
def inspect_sql_index_context(
    connection_name: str,
    confirmation_token: str,
    sql_id: str,
) -> dict[str, Any]:
    """Inspect plan predicates, statistics, and indexes for a SQL ID read-only."""
    connection = _consume_confirmation(connection_name, confirmation_token)
    plan_sql = """
        select child_number,
               plan_hash_value,
               id,
               parent_id,
               operation,
               options,
               object_owner,
               object_name,
               cardinality,
               cost,
               access_predicates,
               filter_predicates
          from v$sql_plan
         where sql_id = :sql_id
         order by child_number, id
    """
    table_stats_sql = """
        select owner,
               table_name,
               num_rows,
               blocks,
               avg_row_len,
               sample_size,
               to_char(last_analyzed, 'YYYY-MM-DD HH24:MI:SS') as last_analyzed
          from dba_tab_statistics
         where owner = :owner
           and table_name = :table_name
           and partition_name is null
    """
    index_sql = """
        select i.owner,
               i.table_name,
               i.index_name,
               i.uniqueness,
               i.status,
               i.visibility,
               i.blevel,
               i.leaf_blocks,
               i.distinct_keys,
               listagg(c.column_name, ', ')
                   within group (order by c.column_position) as columns
          from dba_indexes i
          join dba_ind_columns c
            on c.index_owner = i.owner
           and c.index_name = i.index_name
         where i.table_owner = :owner
           and i.table_name = :table_name
         group by i.owner,
                  i.table_name,
                  i.index_name,
                  i.uniqueness,
                  i.status,
                  i.visibility,
                  i.blevel,
                  i.leaf_blocks,
                  i.distinct_keys
         order by i.index_name
    """
    column_stats_sql = """
        select owner,
               table_name,
               column_name,
               num_distinct,
               num_nulls,
               density,
               histogram,
               num_buckets,
               to_char(last_analyzed, 'YYYY-MM-DD HH24:MI:SS') as last_analyzed
          from dba_tab_col_statistics
         where owner = :owner
           and table_name = :table_name
           and column_name in (
               'UUT_NAME', 'ID', 'UUT_SERIAL_NUMBER', 'UUT_STATUS',
               'FULL_TEST', 'SCHEMA_NAME', 'START_DATE_TIME', 'RUN_ID',
               'RUN_ID_1'
           )
         order by column_name
    """
    with _connect(connection) as database:
        with database.cursor() as cursor:
            cursor.execute(plan_sql, sql_id=sql_id.lower())
            plan = _fetch_dicts(cursor)
            if not plan:
                raise ValueError(f"SQL ID '{sql_id}' is not in V$SQL_PLAN")
            objects = sorted(
                {
                    (row["object_owner"], row["object_name"])
                    for row in plan
                    if row["object_owner"] and row["object_name"]
                    and row["operation"] in {"TABLE ACCESS", "INDEX"}
                }
            )
            metadata = []
            for owner, object_name in objects:
                cursor.execute(
                    table_stats_sql, owner=owner, table_name=object_name
                )
                table_stats = _fetch_dicts(cursor)
                cursor.execute(index_sql, owner=owner, table_name=object_name)
                indexes = _fetch_dicts(cursor)
                cursor.execute(
                    column_stats_sql, owner=owner, table_name=object_name
                )
                column_stats = _fetch_dicts(cursor)
                metadata.append(
                    {
                        "owner": owner,
                        "table_name": object_name,
                        "table_statistics": table_stats,
                        "indexes": indexes,
                        "relevant_column_statistics": column_stats,
                    }
                )
    return {
        "connection_name": connection_name,
        "database": connection["database"],
        "sql_id": sql_id.lower(),
        "plan": plan,
        "object_metadata": metadata,
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
