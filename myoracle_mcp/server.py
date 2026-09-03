from __future__ import annotations

import hashlib
import json
import ctypes
import ctypes.wintypes
from datetime import datetime, timedelta, timezone
import re
import secrets
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import oracledb
import paramiko
import psycopg
from mcp.server.fastmcp import FastMCP


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
CONNECTIONS_FILE = REPOSITORY_ROOT / ".db" / "connections.json"
TOKEN_LIFETIME_SECONDS = 10 * 60

mcp = FastMCP(
    "myoracle",
    instructions=(
        "Oracle tools scoped to this repository. Use the saved connection records "
        "and validate all tool inputs before connecting or changing Oracle state."
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
        "purpose",
    )
    missing = [key for key in required if connection.get(key) in (None, "")]
    if missing:
        raise ValueError(
            f"Connection '{connection_name}' is incomplete; missing: {', '.join(missing)}"
        )
    if str(connection["engine"]).lower() != "oracle":
        raise ValueError(f"Connection '{connection_name}' is not an Oracle connection")
    connection = dict(connection)
    connection["connection_name"] = connection_name
    return connection


def _credential_target(connection_name: str, connection: dict[str, Any]) -> str:
    """Return the configured Windows Credential Manager target."""
    target = str(connection.get("credential_target") or "").strip()
    return target or f"OracleMCP/{connection_name}/SYS"


def _read_windows_credential(target: str) -> str:
    """Read a generic password from Windows Credential Manager."""
    if not hasattr(ctypes, "windll"):
        raise RuntimeError("Windows Credential Manager is only available on Windows")

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", ctypes.wintypes.DWORD),
            ("Type", ctypes.wintypes.DWORD),
            ("TargetName", ctypes.wintypes.LPWSTR),
            ("Comment", ctypes.wintypes.LPWSTR),
            ("LastWritten", ctypes.c_byte * 8),
            ("CredentialBlobSize", ctypes.wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", ctypes.wintypes.DWORD),
            ("AttributeCount", ctypes.wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", ctypes.wintypes.LPWSTR),
            ("UserName", ctypes.wintypes.LPWSTR),
        ]

    credential_ptr = ctypes.POINTER(CREDENTIAL)()
    advapi32 = ctypes.windll.advapi32
    advapi32.CredReadW.argtypes = [
        ctypes.wintypes.LPCWSTR,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(CREDENTIAL)),
    ]
    advapi32.CredReadW.restype = ctypes.wintypes.BOOL
    advapi32.CredFree.argtypes = [ctypes.c_void_p]
    advapi32.CredFree.restype = None

    if not advapi32.CredReadW(target, 1, 0, ctypes.byref(credential_ptr)):
        error = ctypes.get_last_error()
        raise ValueError(
            f"Windows Credential Manager entry not found for target '{target}' "
            f"(error {error})"
        )
    try:
        credential = credential_ptr.contents
        blob = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
        return blob.decode("utf-16-le").rstrip("\x00")
    finally:
        advapi32.CredFree(credential_ptr)


def _fingerprint(connection_name: str, connection: dict[str, Any]) -> str:
    fingerprint_connection = {
        key: value for key, value in connection.items() if key != "password"
    }
    canonical = json.dumps(
        {"name": connection_name, "connection": fingerprint_connection},
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

    password = _read_windows_credential(
        _credential_target(str(connection.get("connection_name", "")), connection)
    )
    kwargs: dict[str, Any] = {
        "user": str(connection["username"]),
        "password": str(password),
        "params": params,
    }
    if mode is not None:
        kwargs["mode"] = mode
    return oracledb.connect(**kwargs)


def _connect_saved_oracle(connection_name: str) -> oracledb.Connection:
    """Connect to a saved Oracle target using its current credentials."""
    return _connect(_read_connection(connection_name))


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


def _ssh_settings(connection_name: str, connection: dict[str, Any]) -> tuple[str, str, int]:
    username = str(connection.get("ssh_username") or "").strip()
    if not username:
        raise ValueError(
            f"Connection '{connection_name}' needs an ssh_username before SSH use"
        )
    target = str(connection.get("ssh_credential_target") or "").strip()
    target = target or f"SSH/{connection['host']}"
    return username, target, int(connection.get("ssh_port", 22))


def _open_ssh(connection_name: str) -> paramiko.SSHClient:
    connection = _read_connection(connection_name)
    username, target, port = _ssh_settings(connection_name, connection)
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(
        hostname=str(connection["host"]),
        port=port,
        username=username,
        password=_read_windows_credential(target),
        look_for_keys=False,
        allow_agent=False,
        timeout=15,
        banner_timeout=15,
        auth_timeout=15,
    )
    return client


@mcp.tool()
def check_ssh_connectivity(connection_name: str) -> dict[str, Any]:
    """Check SSH connectivity for a saved Oracle host without running a command."""
    client = _open_ssh(connection_name)
    try:
        connection = _read_connection(connection_name)
        username, target, port = _ssh_settings(connection_name, connection)
        return {
            "connection_name": connection_name,
            "host": connection["host"],
            "port": port,
            "username": username,
            "credential_target": target,
            "status": "connected",
        }
    finally:
        client.close()


@mcp.tool()
def run_ssh_command(
    connection_name: str, command: str, timeout_seconds: int = 30
) -> dict[str, Any]:
    """Run one explicitly supplied remote SSH command and return its output."""
    command = command.strip()
    if not command:
        raise ValueError("command must not be empty")
    if not 1 <= timeout_seconds <= 300:
        raise ValueError("timeout_seconds must be between 1 and 300")
    client = _open_ssh(connection_name)
    try:
        stdin, stdout, stderr = client.exec_command(
            command, timeout=timeout_seconds, get_pty=False
        )
        exit_status = stdout.channel.recv_exit_status()
        return {
            "connection_name": connection_name,
            "command": command,
            "exit_status": int(exit_status),
            "stdout": stdout.read().decode("utf-8", errors="replace"),
            "stderr": stderr.read().decode("utf-8", errors="replace"),
        }
    finally:
        client.close()


@mcp.tool()
def collect_saved_backup_scripts(
    connection_name: str,
    remote_root: str = "F:/Backup/Oracle/RMAN",
    local_root: str = "rman/scripts",
) -> dict[str, Any]:
    """Copy remote Oracle backup, dependency, and restore scripts into a site folder."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", connection_name):
        raise ValueError("connection_name must be a saved target name")
    if not remote_root or not local_root:
        raise ValueError("remote_root and local_root must not be empty")
    client = _open_ssh(connection_name)
    destination = REPOSITORY_ROOT / local_root / connection_name
    destination.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    try:
        sftp = client.open_sftp()
        try:
            root_stat = sftp.stat(remote_root)
            if not stat.S_ISDIR(root_stat.st_mode):
                relative = Path(remote_root).name
                target = destination / relative
                sftp.get(remote_root, str(target))
                copied.append(str(target.relative_to(REPOSITORY_ROOT)))
                return {"connection_name": connection_name, "remote_root": remote_root, "local_root": str(destination), "copied": copied}

            def walk(path: str) -> None:
                for entry in sftp.listdir_attr(path):
                    remote = f"{path.rstrip('/\\')}/{entry.filename}"
                    if stat.S_ISDIR(entry.st_mode):
                        walk(remote)
                    elif Path(entry.filename).suffix.lower() in {".bat", ".cmd", ".ps1", ".sql", ".vbs", ".xml"}:
                        relative = remote[len(remote_root):].lstrip("/\\").replace("\\", "/")
                        target = destination / Path(relative)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        sftp.get(remote, str(target))
                        copied.append(str(target.relative_to(REPOSITORY_ROOT)))
            walk(remote_root)
        finally:
            sftp.close()
    finally:
        client.close()
    return {"connection_name": connection_name, "remote_root": remote_root, "local_root": str(destination), "copied": copied}


def _powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _remote_error_lines(connection_name: str, paths_expression: str, tail: int) -> dict[str, Any]:
    patterns = r"(?i)error|ora-\d+|rman-\d+|failed|failure|fatal|exception|aborted|no space"
    command = (
        "$ErrorActionPreference='Stop'; "
        f"$rx={_powershell_literal(patterns)}; $files=@({paths_expression}); $out=@(); "
        "foreach($f in $files) { if(Test-Path -LiteralPath $f -PathType Leaf) { "
        f"$n=0; Get-Content -LiteralPath $f -Tail {tail} | ForEach-Object {{ $n++; "
        "if($_ -match $rx) { $out += [pscustomobject]@{file=$f; line=$n; text=$_} } } } } "
        "$out | ConvertTo-Json -Compress -Depth 3"
    )
    client = _open_ssh(connection_name)
    try:
        _, stdout, stderr = client.exec_command(
            "powershell -NoProfile -NonInteractive -Command " + _powershell_literal(command),
            timeout=60, get_pty=False,
        )
        status = stdout.channel.recv_exit_status()
        raw = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        if status:
            raise RuntimeError(err or raw or f"remote command exited {status}")
        parsed = json.loads(raw) if raw else []
        matches = parsed if isinstance(parsed, list) else [parsed]
        return {"matches": matches, "match_count": len(matches)}
    finally:
        client.close()


@mcp.tool()
def inspect_saved_alert_log_errors(connection_name: str, last_records: int = 500) -> dict[str, Any]:
    """Check the saved target's remote Oracle alert log for errors."""
    if not 1 <= last_records <= 5000:
        raise ValueError("last_records must be between 1 and 5000")
    diagnostics = inspect_saved_oracle_diagnostics(connection_name)
    alert_log = diagnostics.get("text_alert_log")
    if not alert_log:
        raise ValueError("Oracle did not return a text alert-log path")
    result = _remote_error_lines(connection_name, _powershell_literal(str(alert_log)), last_records)
    return {"connection_name": connection_name, "log_path": str(alert_log),
            "records_checked": last_records,
            "status": "errors_found" if result["match_count"] else "no_errors_found", **result}


@mcp.tool()
def inspect_saved_backup_log_errors(connection_name: str, remote_log_root: str = "F:/Backup/Oracle/RMAN", last_records: int = 500) -> dict[str, Any]:
    """Scan recent remote Oracle/RMAN backup logs and report errors."""
    if not remote_log_root.strip():
        raise ValueError("remote_log_root must not be empty")
    if not 1 <= last_records <= 5000:
        raise ValueError("last_records must be between 1 and 5000")
    root = _powershell_literal(remote_log_root)
    paths = (f"Get-ChildItem -LiteralPath {root} -Recurse -File -ErrorAction Stop "
             "| Where-Object {$_.Extension -in '.log','.out','.txt'} "
             "| Sort-Object LastWriteTime -Descending | Select-Object -First 20 "
             "| ForEach-Object {$_.FullName}")
    result = _remote_error_lines(connection_name, paths, last_records)
    return {"connection_name": connection_name, "remote_log_root": remote_log_root,
            "files_considered": "up to 20 newest .log/.out/.txt files",
            "records_checked_per_file": last_records,
            "status": "errors_found" if result["match_count"] else "no_errors_found", **result}


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
    """Read and return the full saved connection details without connecting."""
    connection = _read_connection(connection_name)
    token = secrets.token_urlsafe(32)
    now = time.monotonic()
    with _token_lock:
        _purge_expired_tokens(now)
        _pending_confirmations[token] = (
            _fingerprint(connection_name, connection),
            now,
        )
    safe_details = {
        key: value for key, value in connection.items()
        if key not in {"password", "connection_name"}
    }
    safe_details["credential_target"] = _credential_target(connection_name, connection)
    return {
        "connection_name": connection_name,
        "details": safe_details,
        "confirmation_token": token,
        "expires_in_seconds": TOKEN_LIFETIME_SECONDS,
        "note": "The token is retained for backward compatibility and is not required.",
    }


@mcp.tool()
def list_schemas(connection_name: str) -> dict[str, Any]:
    """Connect once and list schemas from a saved Oracle connection."""
    connection = _read_connection(connection_name)
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
def list_custom_jobs(connection_name: str) -> dict[str, Any]:
    """List Scheduler and legacy jobs owned by non-Oracle-maintained users.

    Oracle-maintained owners are excluded using DBA_USERS.
    """
    connection = _read_connection(connection_name)
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
def inspect_saved_database_space(
    connection_name: str,
) -> dict[str, Any]:
    """Read permanent and UNDO tablespace capacity from a saved Oracle connection."""
    connection = _read_connection(connection_name)
    space_sql = """
        select t.tablespace_name,
               t.contents,
               df.allocated_bytes,
               df.max_bytes,
               df.autoextend_files,
               nvl(fs.free_bytes, 0) as free_bytes
          from dba_tablespaces t
          join (
                select tablespace_name,
                       sum(bytes) as allocated_bytes,
                       sum(case when autoextensible = 'YES' then 1 else 0 end)
                           as autoextend_files,
                       sum(maxbytes) as max_bytes
                  from dba_data_files
                 group by tablespace_name
               ) df on df.tablespace_name = t.tablespace_name
          left join (
                select tablespace_name, sum(bytes) as free_bytes
                  from dba_free_space
                 group by tablespace_name
               ) fs on fs.tablespace_name = t.tablespace_name
         where t.contents in ('PERMANENT', 'UNDO')
           and t.status = 'ONLINE'
         order by t.tablespace_name
    """
    with _connect(connection) as database:
        with database.cursor() as cursor:
            cursor.execute(space_sql)
            tablespaces = []
            for row in cursor:
                name, contents, allocated, maximum, autoextend_files, free = row
                allocated_int = int(allocated or 0)
                free_int = int(free or 0)
                maximum_int = int(maximum or 0)
                tablespaces.append({
                    "tablespace_name": str(name),
                    "contents": str(contents),
                    "allocated_bytes": allocated_int,
                    "max_bytes": maximum_int,
                    "autoextend_files": int(autoextend_files or 0),
                    "free_bytes": free_int,
                    "free_percent": round(100 * free_int / allocated_int, 2)
                    if allocated_int else 100.0,
                })
    return {
        "connection_name": connection_name,
        "database": connection["database"],
        "tablespace_count": len(tablespaces),
        "tablespaces": tablespaces,
    }


@mcp.tool()
def inspect_all_saved_database_space() -> dict[str, Any]:
    """Read tablespace capacity from every saved Oracle target."""
    results = []
    for connection_name in connections_list():
        try:
            results.append({
                "connection_name": connection_name,
                "ok": True,
                "result": inspect_saved_database_space(connection_name),
            })
        except Exception as exc:
            results.append({
                "connection_name": connection_name,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            })
    return {"target_count": len(results), "results": results}


@mcp.tool()
def inspect_local_rag_database() -> dict[str, Any]:
    """Check local RAG PostgreSQL, pgvector, and required tables."""
    connection = _read_connection("local_rag")
    url = (
        f"postgresql://{connection['username']}:{connection['password']}@"
        f"{connection['host']}:{connection['port']}/{connection['database']}"
    )
    with psycopg.connect(url) as database:
        row = database.execute("""
            select current_database(),
                   exists (select 1 from pg_extension where extname = 'vector'),
                   to_regclass('public.rag_documents'),
                   to_regclass('public.rag_chunks')
        """).fetchone()
    return {
        "database": row[0],
        "pgvector_installed": bool(row[1]),
        "rag_documents_table": str(row[2]) if row[2] else None,
        "rag_chunks_table": str(row[3]) if row[3] else None,
        "healthy": bool(row[1] and row[2] and row[3]),
    }


@mcp.tool()
def ingest_local_rag_markdown(path: str = "local_rag") -> dict[str, Any]:
    """Ingest Markdown files into the repository PostgreSQL RAG through its CLI."""
    source = (REPOSITORY_ROOT / path).resolve()
    if REPOSITORY_ROOT not in source.parents and source != REPOSITORY_ROOT:
        raise ValueError("path must remain inside the repository")
    if source.is_file() and source.suffix.lower() != ".md":
        raise ValueError("path must be a Markdown file or directory")
    if not source.exists():
        raise ValueError(f"path does not exist: {path}")
    command = [sys.executable, str(REPOSITORY_ROOT / "local_rag" / "rag.py"), "ingest", str(source)]
    completed = subprocess.run(command, cwd=str(REPOSITORY_ROOT), capture_output=True, text=True, timeout=300)
    if completed.returncode:
        raise RuntimeError((completed.stderr or completed.stdout).strip() or "RAG ingestion failed")
    return {"path": str(source), "output": completed.stdout.strip()}


@mcp.tool()
def list_top_full_scan_queries(
    connection_name: str,
    limit: int = 10,
) -> dict[str, Any]:
    """Rank custom shared-pool SQL with full table scans by physical reads.

    Custom SQL means the parsing schema has DBA_USERS.ORACLE_MAINTAINED = 'N'.
    Statistics are aggregated across child cursors by SQL ID from V$SQL, and a
    qualifying child plan must contain TABLE ACCESS FULL in V$SQL_PLAN.
    """
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    connection = _read_connection(connection_name)
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
    sql_id: str,
) -> dict[str, Any]:
    """Inspect plan predicates, statistics, and indexes for a SQL ID read-only."""
    connection = _read_connection(connection_name)
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


def inspect_oracle_connection_spreadsheet(file_path: str) -> dict[str, object]:
    """Read non-secret Oracle connection metadata from an XLSX or ODS spreadsheet.

    Passwords, tokens, credential references, and private-key columns are
    deliberately skipped. The result is read-only and does not connect to
    Oracle or any other service.
    """
    path = Path(file_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Spreadsheet not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        tables = _xlsx_tables(path)
    elif suffix == ".ods":
        tables = _ods_tables(path)
    else:
        raise ValueError("Only .xlsx and .ods files are supported.")
    records, ignored_columns = _connection_metadata(tables)
    return {
        "source_file": path.name,
        "records": records,
        "ignored_secret_columns": ignored_columns,
        "record_count": len(records),
    }

def expand_saved_tablespace(connection_name: str, tablespace_name: str, additional_gib: int) -> dict[str, object]:
    """Permanently add one non-autoextending datafile to a saved tablespace.

    This is a write operation. It uses a Windows Credential Manager-backed
    saved connection, validates identifiers and capacity, then returns the
    before/after capacity figures. The datafile is placed alongside an existing
    file for the tablespace, unless Oracle Managed Files is enabled.
    """
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_$#]{0,29}", tablespace_name):
        raise ValueError("tablespace_name must be a simple Oracle identifier.")
    if not 1 <= additional_gib <= 1024:
        raise ValueError("additional_gib must be between 1 and 1024.")
    safe_name = tablespace_name.upper()
    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select sum(bytes), sum(case when autoextensible='YES' then maxbytes else bytes end) "
                "from dba_data_files where tablespace_name = :name",
                {"name": safe_name},
            )
            before_allocated, before_maximum = cursor.fetchone()
            if before_allocated is None:
                raise ValueError(f"Tablespace {safe_name!r} has no datafiles.")
            cursor.execute(
                "select bigfile from dba_tablespaces where tablespace_name = :name",
                {"name": safe_name},
            )
            tablespace_row = cursor.fetchone()
            if tablespace_row is None:
                raise ValueError(f"Tablespace {safe_name!r} was not found.")
            is_bigfile = str(tablespace_row[0]).upper() == "YES"
            cursor.execute("select value from v$parameter where name = 'db_block_size'")
            db_block_size = int((cursor.fetchone() or [8192])[0])
            # Smallfile datafiles are limited to 4,194,303 blocks. Leave a
            # small margin so Oracle does not reject a boundary-size request.
            max_file_gib = 1024 if is_bigfile else max(
                1, ((4_194_303 * db_block_size) // (1024 ** 3)) - 1
            )
            cursor.execute("select value from v$parameter where name = 'db_create_file_dest'")
            omf_destination = (cursor.fetchone() or [""])[0] or ""
            if not omf_destination:
                cursor.execute(
                    "select file_name from dba_data_files where tablespace_name = :name order by file_id fetch first 1 rows only",
                    {"name": safe_name},
                )
                source_file = cursor.fetchone()[0]
                separator = "\\" if source_file.rfind("\\") > source_file.rfind("/") else "/"
                directory = source_file.rsplit(separator, 1)[0]
            remaining_gib = additional_gib
            added_datafiles: list[int] = []
            suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            sequence = 1
            while remaining_gib:
                file_gib = min(remaining_gib, max_file_gib)
                if omf_destination:
                    datafile_clause = " DATAFILE"
                else:
                    datafile_clause = (
                        f" DATAFILE '{directory}{separator}{safe_name.lower()}_capacity_{suffix}_{sequence}.dbf'"
                    )
                cursor.execute(
                    f"alter tablespace {safe_name} add{datafile_clause} size {file_gib}G autoextend off"
                )
                added_datafiles.append(file_gib)
                remaining_gib -= file_gib
                sequence += 1
            connection.commit()
            cursor.execute(
                "select sum(bytes), sum(case when autoextensible='YES' then maxbytes else bytes end) "
                "from dba_data_files where tablespace_name = :name",
                {"name": safe_name},
            )
            after_allocated, after_maximum = cursor.fetchone()
        return {
            "connection": connection_name,
            "tablespace_name": safe_name,
            "added_gib": additional_gib,
            "before_allocated_bytes": int(before_allocated),
            "before_max_bytes": int(before_maximum),
            "after_allocated_bytes": int(after_allocated),
            "after_max_bytes": int(after_maximum),
            "datafiles_added_gib": added_datafiles,
        }
    finally:
        connection.close()

def test_saved_table_compression(connection_name: str, confirmed: bool) -> dict[str, object]:
    """Create and immediately remove a disposable basic-compression table.

    The probe is restricted to the saved PH connection. It returns Oracle's
    feature error if compression is unavailable; no table is retained after a
    successful create.
    """
    if not confirmed:
        raise ValueError("confirmed=true is required for this write operation.")
    if connection_name != "PH":
        raise ValueError("This compression probe is restricted to the PH connection.")
    table_name = f"CX_COMP_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            try:
                cursor.execute(f"CREATE TABLE {table_name} (id NUMBER) COMPRESS")
            except oracledb.DatabaseError as exc:
                error, = exc.args
                return {
                    "connection": connection_name,
                    "table_name": table_name,
                    "compression_enabled": False,
                    "oracle_error": str(error),
                }
            cursor.execute(f"DROP TABLE {table_name} PURGE")
        return {
            "connection": connection_name,
            "table_name": table_name,
            "compression_enabled": True,
            "cleanup": "dropped",
        }
    finally:
        connection.close()

def inspect_saved_compressed_tables(connection_name: str) -> dict[str, object]:
    """List compressed tables owned by non-Oracle-maintained schemas."""
    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select t.owner, t.table_name, t.compression, t.compress_for "
                "from dba_tables t join dba_users u on u.username = t.owner "
                "where t.compression = 'ENABLED' and u.oracle_maintained = 'N' "
                "order by t.owner, t.table_name"
            )
            tables = [
                {
                    "owner": str(owner),
                    "table_name": str(table_name),
                    "compression": str(compression),
                    "compress_for": str(compress_for) if compress_for else None,
                }
                for owner, table_name, compression, compress_for in cursor
            ]
        return {"connection": connection_name, "compressed_tables": tables, "count": len(tables)}
    finally:
        connection.close()

def search_saved_scheduler_job_history(connection_name: str, search_term: str) -> dict[str, object]:
    """Search Scheduler run history output and diagnostics for a text term."""
    term = search_term.strip()
    if not 1 <= len(term) <= 128:
        raise ValueError("search_term must contain between 1 and 128 characters.")
    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select log_date, owner, job_name, status, error#, additional_info, output "
                "from dba_scheduler_job_run_details "
                "where upper(nvl(additional_info, ' ') || ' ' || nvl(output, ' ')) like :pattern "
                "order by log_date desc",
                {"pattern": f"%{term.upper()}%"},
            )
            runs = [
                {
                    "log_date": str(log_date),
                    "owner": str(owner),
                    "job_name": str(job_name),
                    "status": str(status),
                    "error_number": int(error_number) if error_number is not None else None,
                    "additional_info": str(additional_info) if additional_info else None,
                    "output": str(output) if output else None,
                }
                for log_date, owner, job_name, status, error_number, additional_info, output in cursor
            ]
        return {"connection": connection_name, "search_term": term, "runs": runs, "count": len(runs)}
    finally:
        connection.close()

def inspect_saved_scheduler_job(
    connection_name: str, job_name: str, history_days: int = 30
) -> dict[str, object]:
    """Inspect a saved Oracle Scheduler job definition and dated run history.

    This read-only diagnostic returns the matching ``DBA_SCHEDULER_JOBS``
    definition, including its action and recurrence, plus all run details from
    the requested trailing date window. It never returns credentials.
    """
    safe_job_name = job_name.strip().upper()
    if not 1 <= len(safe_job_name) <= 128:
        raise ValueError("job_name must contain between 1 and 128 characters.")
    safe_history_days = int(history_days)
    if not 1 <= safe_history_days <= 365:
        raise ValueError("history_days must be between 1 and 365.")
    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select owner, job_name, enabled, state, job_type, job_action, program_owner, program_name, "
                "schedule_owner, schedule_name, repeat_interval, "
                "to_char(start_date, 'YYYY-MM-DD HH24:MI:SS TZH:TZM'), "
                "to_char(next_run_date, 'YYYY-MM-DD HH24:MI:SS TZH:TZM'), "
                "to_char(last_start_date, 'YYYY-MM-DD HH24:MI:SS TZH:TZM'), "
                "run_count, failure_count, logging_level, store_output, comments "
                "from dba_scheduler_jobs where upper(job_name) = :job_name order by owner",
                {"job_name": safe_job_name},
            )
            jobs = [
                {
                    "owner": str(owner),
                    "job_name": str(name),
                    "enabled": str(enabled),
                    "state": str(state),
                    "job_type": str(job_type) if job_type else None,
                    "job_action": str(job_action) if job_action else None,
                    "program_owner": str(program_owner) if program_owner else None,
                    "program_name": str(program_name) if program_name else None,
                    "schedule_owner": str(schedule_owner) if schedule_owner else None,
                    "schedule_name": str(schedule_name) if schedule_name else None,
                    "repeat_interval": str(repeat_interval) if repeat_interval else None,
                    "start_date": str(start_date) if start_date else None,
                    "next_run_date": str(next_run_date) if next_run_date else None,
                    "last_start_date": str(last_start_date) if last_start_date else None,
                    "run_count": int(run_count or 0),
                    "failure_count": int(failure_count or 0),
                    "logging_level": str(logging_level) if logging_level else None,
                    "store_output": str(store_output) if store_output else None,
                    "comments": str(comments) if comments else None,
                }
                for owner, name, enabled, state, job_type, job_action, program_owner, program_name,
                schedule_owner, schedule_name, repeat_interval, start_date, next_run_date, last_start_date,
                run_count, failure_count, logging_level, store_output, comments in cursor
            ]
            cursor.execute(
                "select to_char(log_date, 'YYYY-MM-DD HH24:MI:SS TZH:TZM'), owner, job_name, status, error#, additional_info, output, "
                "to_char(req_start_date, 'YYYY-MM-DD HH24:MI:SS TZH:TZM'), "
                "to_char(actual_start_date, 'YYYY-MM-DD HH24:MI:SS TZH:TZM'), "
                "to_char(run_duration), instance_id "
                "from dba_scheduler_job_run_details where upper(job_name) = :job_name "
                "and log_date >= systimestamp - numtodsinterval(:history_days, 'DAY') "
                "order by log_date desc",
                {"job_name": safe_job_name, "history_days": safe_history_days},
            )
            runs = [
                {
                    "log_date": str(log_date),
                    "owner": str(owner),
                    "job_name": str(name),
                    "status": str(status),
                    "error_number": int(error_number) if error_number is not None else None,
                    "additional_info": str(additional_info) if additional_info else None,
                    "output": str(output) if output else None,
                    "requested_start": str(requested_start) if requested_start else None,
                    "actual_start": str(actual_start) if actual_start else None,
                    "run_duration": str(run_duration) if run_duration else None,
                    "instance_id": int(instance_id) if instance_id is not None else None,
                }
                for log_date, owner, name, status, error_number, additional_info, output,
                requested_start, actual_start, run_duration, instance_id in cursor
            ]
        return {
            "connection": connection_name,
            "job_name": safe_job_name,
            "history_days": safe_history_days,
            "jobs": jobs,
            "runs": runs,
        }
    finally:
        connection.close()

def inspect_saved_schema_sql_execution_plans(
    connection_name: str, schema_name: str, search_terms: list[str], history_days: int = 30
) -> dict[str, object]:
    """Inspect retained plans for SQL from one schema on any saved Oracle target.

    The read-only diagnostic searches recent ``V$SQL`` cursors for one parsing
    schema and one to three SQL-text terms, returns every matching retained
    child-cursor plan, and inventories statistics and indexes for physical
    tables referenced by those plans. It never executes the matched SQL.
    """
    safe_schema = schema_name.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_$#]{0,127}", safe_schema):
        raise ValueError("schema_name must be a valid Oracle schema identifier.")
    safe_terms = [term.strip().upper() for term in search_terms if term.strip()]
    if not 1 <= len(safe_terms) <= 3:
        raise ValueError("search_terms must contain between 1 and 3 non-empty terms.")
    if any(len(term) > 128 for term in safe_terms):
        raise ValueError("Each search term must contain at most 128 characters.")
    safe_history_days = int(history_days)
    if not 1 <= safe_history_days <= 365:
        raise ValueError("history_days must be between 1 and 365.")
    predicates = " or ".join(f"upper(q.sql_text) like :term{index}" for index in range(len(safe_terms)))
    binds: dict[str, object] = {"schema_name": safe_schema, "history_days": safe_history_days}
    binds.update({f"term{index}": f"%{term}%" for index, term in enumerate(safe_terms)})
    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select q.sql_id, q.child_number, q.module, q.action, c.command_name, q.executions, "
                "q.elapsed_time, q.cpu_time, q.buffer_gets, q.disk_reads, q.rows_processed, "
                "to_char(q.last_active_time, 'YYYY-MM-DD HH24:MI:SS'), dbms_lob.substr(q.sql_fulltext, 4000, 1) "
                "from v$sql q left join v$sqlcommand c on c.command_type = q.command_type "
                "where upper(q.parsing_schema_name) = :schema_name "
                "and q.last_active_time >= systimestamp - numtodsinterval(:history_days, 'DAY') "
                f"and ({predicates}) order by q.last_active_time desc nulls last",
                binds,
            )
            statement_rows = list(cursor)
            statements = []
            table_objects: set[tuple[str, str]] = set()
            for sql_id, child_number, module, action, command, executions, elapsed, cpu, buffer_gets, disk_reads, rows_processed, last_active, sql_text in statement_rows:
                cursor.execute(
                    "select id, parent_id, depth, operation, options, object_owner, object_name, object_type, "
                    "cardinality, cost, bytes, dbms_lob.substr(access_predicates, 1000, 1), "
                    "dbms_lob.substr(filter_predicates, 1000, 1) "
                    "from v$sql_plan where sql_id = :sql_id and child_number = :child_number order by id",
                    {"sql_id": sql_id, "child_number": child_number},
                )
                plan = []
                for plan_id, parent_id, depth, operation, options, object_owner, object_name, object_type, cardinality, cost, bytes_value, access_predicates, filter_predicates in cursor:
                    if object_owner and object_name and object_type and "TABLE" in str(object_type).upper():
                        table_objects.add((str(object_owner).upper(), str(object_name).upper()))
                    plan.append({"id": int(plan_id), "parent_id": int(parent_id) if parent_id is not None else None,
                                 "depth": int(depth), "operation": str(operation), "options": str(options) if options else None,
                                 "object_owner": str(object_owner) if object_owner else None, "object_name": str(object_name) if object_name else None,
                                 "object_type": str(object_type) if object_type else None, "cardinality": int(cardinality) if cardinality is not None else None,
                                 "cost": int(cost) if cost is not None else None, "bytes": int(bytes_value) if bytes_value is not None else None,
                                 "access_predicates": str(access_predicates) if access_predicates else None,
                                 "filter_predicates": str(filter_predicates) if filter_predicates else None})
                statements.append({"sql_id": str(sql_id), "child_number": int(child_number), "module": str(module) if module else None,
                                   "action": str(action) if action else None, "command": str(command) if command else None,
                                   "executions": int(executions or 0), "elapsed_time_microseconds": int(elapsed or 0),
                                   "cpu_time_microseconds": int(cpu or 0), "buffer_gets": int(buffer_gets or 0),
                                   "disk_reads": int(disk_reads or 0), "rows_processed": int(rows_processed or 0),
                                   "last_active_time": str(last_active), "sql_text": str(sql_text) if sql_text else None, "plan": plan})
            objects = []
            for owner, table_name in sorted(table_objects):
                cursor.execute("select num_rows, blocks, last_analyzed, stale_stats from dba_tab_statistics where owner = :owner and table_name = :table_name",
                               {"owner": owner, "table_name": table_name})
                statistics = cursor.fetchone()
                cursor.execute(
                    "select c.index_name, i.status, i.visibility, i.uniqueness, "
                    "listagg(c.column_name, ', ') within group (order by c.column_position) "
                    "from dba_ind_columns c join dba_indexes i on i.owner = c.index_owner and i.index_name = c.index_name "
                    "and i.table_owner = c.table_owner and i.table_name = c.table_name "
                    "where c.table_owner = :owner and c.table_name = :table_name "
                    "group by c.index_name, i.status, i.visibility, i.uniqueness order by c.index_name",
                    {"owner": owner, "table_name": table_name},
                )
                indexes = [{"index_name": str(index_name), "status": str(status), "visibility": str(visibility),
                            "uniqueness": str(uniqueness), "columns": str(columns)}
                           for index_name, status, visibility, uniqueness, columns in cursor]
                objects.append({"owner": owner, "table_name": table_name,
                                "statistics": ({"num_rows": int(statistics[0]) if statistics and statistics[0] is not None else None,
                                                "blocks": int(statistics[1]) if statistics and statistics[1] is not None else None,
                                                "last_analyzed": str(statistics[2]) if statistics and statistics[2] else None,
                                                "stale_stats": str(statistics[3]) if statistics and statistics[3] else None}),
                                "indexes": indexes})
        return {"connection": connection_name, "schema_name": safe_schema, "search_terms": safe_terms,
                "history_days": safe_history_days, "statements": statements, "referenced_tables": objects}
    finally:
        connection.close()

def inspect_saved_materialized_view_refreshes(connection_name: str) -> dict[str, object]:
    """Read active materialized-view refresh activity from a saved Oracle connection.

    The result combines active database sessions and in-progress long
    operations. It is read-only and never returns credentials.
    """
    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select s.sid, s.serial#, s.username, s.module, s.action, s.sql_id, "
                "dbms_lob.substr(q.sql_fulltext, 1000, 1) sql_text "
                "from v$session s left join v$sql q on q.sql_id=s.sql_id and q.child_number=s.sql_child_number "
                "where s.username is not null and s.sid != sys_context('USERENV', 'SID') and "
                "(upper(nvl(s.module, ' ')) like '%MVIEW%' or upper(nvl(s.action, ' ')) like '%MVIEW%' "
                "or upper(nvl(q.sql_fulltext, ' ')) like '%DBMS_MVIEW%' "
                "or upper(nvl(q.sql_fulltext, ' ')) like '%MV_REFRESH%') "
                "order by s.sid"
            )
            active_sessions = [
                {"sid": int(sid), "serial": int(serial), "username": str(username) if username else None,
                 "module": str(module) if module else None, "action": str(action) if action else None,
                 "sql_id": str(sql_id) if sql_id else None, "sql_text": str(sql_text) if sql_text else None}
                for sid, serial, username, module, action, sql_id, sql_text in cursor
            ]
            cursor.execute(
                "select sid, serial#, opname, target, target_desc, sofar, totalwork, units, "
                "elapsed_seconds, time_remaining "
                "from v$session_longops where sofar < totalwork and totalwork > 0 and "
                "(upper(nvl(opname, ' ')) like '%MVIEW%' or upper(nvl(target_desc, ' ')) like '%MATERIALIZED VIEW%') "
                "order by start_time"
            )
            long_operations = [
                {"sid": int(sid), "serial": int(serial), "operation": str(operation), "target": str(target) if target else None,
                 "target_description": str(description) if description else None, "sofar": int(sofar), "totalwork": int(totalwork),
                 "units": str(units) if units else None, "elapsed_seconds": int(elapsed or 0), "time_remaining_seconds": int(remaining or 0)}
                for sid, serial, operation, target, description, sofar, totalwork, units, elapsed, remaining in cursor
            ]
        return {"connection": connection_name, "active_sessions": active_sessions,
                "long_operations": long_operations}
    finally:
        connection.close()

def inspect_saved_materialized_view_refresh_waits(connection_name: str) -> dict[str, object]:
    """Read current wait and blocking details for active materialized-view refresh sessions.

    This read-only check identifies sessions using the same materialized-view
    refresh criteria as the activity inspector. It reports the point-in-time
    wait event, wait class, wait duration, and local blocking-session chain.
    """
    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select s.sid, s.serial#, s.username, s.status, s.module, s.action, s.sql_id, "
                "s.event, s.wait_class, s.state, s.seconds_in_wait, s.wait_time_micro, "
                "s.blocking_instance, s.blocking_session, s.blocking_session_status, "
                "s.final_blocking_instance, s.final_blocking_session, s.final_blocking_session_status "
                "from v$session s left join v$sql q on q.sql_id=s.sql_id and q.child_number=s.sql_child_number "
                "where s.username is not null and s.sid != sys_context('USERENV', 'SID') and "
                "(upper(nvl(s.module, ' ')) like '%MVIEW%' or upper(nvl(s.action, ' ')) like '%MVIEW%' "
                "or upper(nvl(q.sql_fulltext, ' ')) like '%DBMS_MVIEW%' "
                "or upper(nvl(q.sql_fulltext, ' ')) like '%MV_REFRESH%') "
                "order by s.sid"
            )
            sessions = [
                {
                    "sid": int(sid),
                    "serial": int(serial),
                    "username": str(username) if username else None,
                    "status": str(status),
                    "module": str(module) if module else None,
                    "action": str(action) if action else None,
                    "sql_id": str(sql_id) if sql_id else None,
                    "event": str(event) if event else None,
                    "wait_class": str(wait_class) if wait_class else None,
                    "wait_state": str(wait_state) if wait_state else None,
                    "seconds_in_wait": int(seconds_in_wait or 0),
                    "wait_time_microseconds": int(wait_time_micro or 0),
                    "blocking_instance": int(blocking_instance) if blocking_instance is not None else None,
                    "blocking_session": int(blocking_session) if blocking_session is not None else None,
                    "blocking_session_status": str(blocking_status) if blocking_status else None,
                    "final_blocking_instance": int(final_blocking_instance) if final_blocking_instance is not None else None,
                    "final_blocking_session": int(final_blocking_session) if final_blocking_session is not None else None,
                    "final_blocking_session_status": str(final_blocking_status) if final_blocking_status else None,
                }
                for sid, serial, username, status, module, action, sql_id, event, wait_class,
                wait_state, seconds_in_wait, wait_time_micro, blocking_instance, blocking_session,
                blocking_status, final_blocking_instance, final_blocking_session, final_blocking_status in cursor
            ]
        return {"connection": connection_name, "sessions": sessions}
    finally:
        connection.close()

def inspect_saved_sync_process_status(connection_name: str, history_days: int = 7) -> dict[str, object]:
    """Return the current status of the TRANSFER_USER materialized-view sync process.

    The standalone ``refresh_mv.py`` process identifies active workers with
    ``MODULE=DAILY_TRANSFER_PY`` and writes completed or failed site outcomes
    to ``TRANSFER_USER.LOG_PROCEDURE`` as ``DAILY_TRANSFER`` records. This
    read-only diagnostic combines those lifecycle records with active worker
    sessions, matching long operations, and current refresh metadata for the
    ``TRANSFER_USER`` materialized views. Audit history is limited by date,
    defaulting to the trailing seven days. It never returns credentials or data.
    """
    safe_history_days = int(history_days)
    if not 1 <= safe_history_days <= 90:
        raise ValueError("history_days must be between 1 and 90.")
    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select s.sid, s.serial#, s.status, s.username, s.action, s.sql_id, "
                "s.event, s.wait_class, s.seconds_in_wait "
                "from v$session s where s.module = 'DAILY_TRANSFER_PY' "
                "and s.sid != sys_context('USERENV', 'SID') order by s.sid"
            )
            active_workers = [
                {
                    "sid": int(sid),
                    "serial": int(serial),
                    "status": str(status),
                    "username": str(username) if username else None,
                    "site": str(action) if action else None,
                    "sql_id": str(sql_id) if sql_id else None,
                    "event": str(event) if event else None,
                    "wait_class": str(wait_class) if wait_class else None,
                    "seconds_in_wait": int(seconds_in_wait or 0),
                }
                for sid, serial, status, username, action, sql_id, event, wait_class, seconds_in_wait in cursor
            ]
            cursor.execute(
                "select l.sid, l.serial#, l.opname, l.target, l.sofar, l.totalwork, l.units, "
                "l.elapsed_seconds, l.time_remaining "
                "from v$session_longops l join v$session s on s.sid = l.sid and s.serial# = l.serial# "
                "where s.module = 'DAILY_TRANSFER_PY' and l.sofar < l.totalwork and l.totalwork > 0 "
                "order by l.start_time"
            )
            active_long_operations = [
                {
                    "sid": int(sid),
                    "serial": int(serial),
                    "operation": str(operation),
                    "target": str(target) if target else None,
                    "sofar": int(sofar),
                    "totalwork": int(totalwork),
                    "units": str(units) if units else None,
                    "elapsed_seconds": int(elapsed or 0),
                    "time_remaining_seconds": int(remaining or 0),
                }
                for sid, serial, operation, target, sofar, totalwork, units, elapsed, remaining in cursor
            ]
            cursor.execute(
                "select proc_state, proc_start, proc_end, proc_input, proc_output, proc_user, proc_system "
                "from transfer_user.log_procedure where proc_name = 'DAILY_TRANSFER' "
                "and proc_start >= systimestamp - numtodsinterval(:history_days, 'DAY') "
                "order by proc_start desc nulls last",
                {"history_days": safe_history_days},
            )
            recent_runs = [
                {
                    "state": str(state) if state else None,
                    "started_at": str(started_at) if started_at else None,
                    "ended_at": str(ended_at) if ended_at else None,
                    "input": str(input_text) if input_text else None,
                    "output": str(output_text) if output_text else None,
                    "user": str(user) if user else None,
                    "system": str(system) if system else None,
                }
                for state, started_at, ended_at, input_text, output_text, user, system in cursor
            ]
            cursor.execute(
                "select mview_name, last_refresh_date, staleness, compile_state "
                "from dba_mviews where owner = 'TRANSFER_USER' order by mview_name"
            )
            materialized_views = [
                {
                    "name": str(name),
                    "last_refresh_date": str(last_refresh_date) if last_refresh_date else None,
                    "staleness": str(staleness) if staleness else None,
                    "compile_state": str(compile_state) if compile_state else None,
                }
                for name, last_refresh_date, staleness, compile_state in cursor
            ]
        latest_state = recent_runs[0]["state"].upper() if recent_runs and recent_runs[0]["state"] else None
        if active_workers:
            status = "running"
        elif latest_state == "ERROR":
            status = "failed"
        elif latest_state == "END":
            status = "completed"
        else:
            status = "unknown"
        return {
            "connection": connection_name,
            "history_days": safe_history_days,
            "status": status,
            "active_workers": active_workers,
            "active_long_operations": active_long_operations,
            "recent_runs": recent_runs,
            "materialized_views": materialized_views,
        }
    finally:
        connection.close()

def kill_saved_oracle_session(connection_name: str, sid: int, serial: int) -> dict[str, object]:
    """Immediately terminate one explicitly identified Oracle session.

    This is a write operation. The caller must obtain explicit approval before
    invoking it. The session is located by both SID and serial number before
    Oracle receives ``ALTER SYSTEM KILL SESSION ... IMMEDIATE``.
    """
    safe_sid = int(sid)
    safe_serial = int(serial)
    if not 1 <= safe_sid <= 2_147_483_647 or not 1 <= safe_serial <= 2_147_483_647:
        raise ValueError("sid and serial must be positive Oracle session identifiers.")
    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select username, status, module, action from v$session where sid = :sid and serial# = :serial",
                {"sid": safe_sid, "serial": safe_serial},
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError(f"Session {safe_sid},{safe_serial} is not currently present.")
            username, status, module, action = row
            cursor.execute(f"alter system kill session '{safe_sid},{safe_serial}' immediate")
        return {
            "connection": connection_name,
            "sid": safe_sid,
            "serial": safe_serial,
            "username": str(username) if username else None,
            "status_before_kill": str(status) if status else None,
            "module": str(module) if module else None,
            "action": str(action) if action else None,
            "result": "kill_requested",
        }
    finally:
        connection.close()

def set_saved_oracle_session_trace(
    connection_name: str,
    sid: int,
    serial: int,
    enabled: bool,
    confirmed: bool = False,
    waits: bool = True,
    binds: bool = False,
) -> dict[str, object]:
    """Enable or disable SQL tracing for one explicitly identified Oracle session.

    This is a write operation and requires ``confirmed=true`` after explicit
    user approval. It verifies the SID and serial number immediately before
    calling ``DBMS_MONITOR.SESSION_TRACE_ENABLE`` or
    ``DBMS_MONITOR.SESSION_TRACE_DISABLE``. Wait events are collected by
    default; bind values are disabled by default to avoid recording sensitive
    values in the database trace file.
    """
    safe_sid = int(sid)
    safe_serial = int(serial)
    if not 1 <= safe_sid <= 2_147_483_647 or not 1 <= safe_serial <= 2_147_483_647:
        raise ValueError("sid and serial must be positive Oracle session identifiers.")
    if confirmed is not True:
        raise ValueError("Set confirmed=true only after explicit approval to change session tracing.")

    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select username, status, module, action from v$session where sid = :sid and serial# = :serial",
                {"sid": safe_sid, "serial": safe_serial},
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError(f"Session {safe_sid},{safe_serial} is not currently present.")
            username, status, module, action = row
            if enabled:
                cursor.execute(
                    "begin dbms_monitor.session_trace_enable("
                    "session_id => :sid, serial_num => :serial, waits => "
                    f"{'true' if waits else 'false'}, binds => {'true' if binds else 'false'}); end;",
                    {"sid": safe_sid, "serial": safe_serial},
                )
            else:
                cursor.execute(
                    "begin dbms_monitor.session_trace_disable("
                    "session_id => :sid, serial_num => :serial); end;",
                    {"sid": safe_sid, "serial": safe_serial},
                )
        return {
            "connection": connection_name,
            "sid": safe_sid,
            "serial": safe_serial,
            "username": str(username) if username else None,
            "status_before_change": str(status) if status else None,
            "module": str(module) if module else None,
            "action": str(action) if action else None,
            "trace_enabled": bool(enabled),
            "waits": bool(waits) if enabled else None,
            "binds": bool(binds) if enabled else None,
        }
    finally:
        connection.close()

def set_saved_all_users_login_trace(
    connection_name: str, enabled: bool, confirmed: bool = False
) -> dict[str, object]:
    """Create or remove the all-users Oracle logon tracing trigger.

    This is a write operation and requires ``confirmed=true`` after explicit
    user approval. When enabled, it creates only ``SYS.ALL_USERS_LOGIN_TRACE``
    on the selected saved database. The trigger labels new trace files with
    ``ALL_USERS`` and enables 10046 level-8 tracing (SQL plus waits, without
    bind values). It suppresses tracing errors so a failed trace setup never
    prevents a user from logging in.
    """
    if confirmed is not True:
        raise ValueError("Set confirmed=true only after explicit approval to change all-users login tracing.")

    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            if enabled:
                cursor.execute(
                    "create or replace trigger SYS.ALL_USERS_LOGIN_TRACE "
                    "after logon on database "
                    "begin "
                    "execute immediate 'alter session set tracefile_identifier = ''ALL_USERS'''; "
                    "execute immediate q'[alter session set events '10046 trace name context forever, level 8']'; "
                    "exception when others then null; end;"
                )
            else:
                cursor.execute(
                    "select status from dba_triggers where owner = 'SYS' and trigger_name = 'ALL_USERS_LOGIN_TRACE'"
                )
                if cursor.fetchone() is None:
                    raise ValueError("Trigger SYS.ALL_USERS_LOGIN_TRACE does not exist.")
                cursor.execute("drop trigger SYS.ALL_USERS_LOGIN_TRACE")

            cursor.execute(
                "select status, triggering_event, trigger_type from dba_triggers "
                "where owner = 'SYS' and trigger_name = 'ALL_USERS_LOGIN_TRACE'"
            )
            row = cursor.fetchone()
        return {
            "connection": connection_name,
            "trigger": "SYS.ALL_USERS_LOGIN_TRACE",
            "trace_enabled": bool(enabled),
            "trigger_status": str(row[0]) if row else None,
            "triggering_event": str(row[1]) if row else None,
            "trigger_type": str(row[2]) if row else None,
            "trace_identifier": "ALL_USERS" if enabled else None,
            "trace_level": 8 if enabled else None,
            "binds_collected": False if enabled else None,
        }
    finally:
        connection.close()

def recreate_saved_sequence_without_cache(
    connection_name: str, owner: str, sequence_name: str, confirmed: bool = False
) -> dict[str, object]:
    """Recreate one sequence with NOCACHE and compile invalid direct dependents.

    This is a write operation and requires ``confirmed=true`` after explicit
    user approval. It obtains the current persisted next value from
    ``DBA_SEQUENCES.LAST_NUMBER``, recreates the sequence from its metadata
    with ``START WITH`` set to that value and ``NOCACHE``, then compiles direct
    invalid PL/SQL dependents. Stop concurrent ``NEXTVAL`` use before calling:
    sequence values can otherwise advance between inspection and recreation.
    """
    safe_owner = str(owner).upper()
    safe_sequence_name = str(sequence_name).upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_$#]{0,29}", safe_owner):
        raise ValueError("owner must be a simple Oracle identifier.")
    if not re.fullmatch(r"[A-Z][A-Z0-9_$#]{0,29}", safe_sequence_name):
        raise ValueError("sequence_name must be a simple Oracle identifier.")
    if confirmed is not True:
        raise ValueError("Set confirmed=true only after explicit approval to recreate the sequence.")

    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select last_number from dba_sequences where sequence_owner = :owner and sequence_name = :name",
                {"owner": safe_owner, "name": safe_sequence_name},
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError(f"Sequence {safe_owner}.{safe_sequence_name} was not found.")
            next_value = int(row[0])
            cursor.execute(
                "select dbms_metadata.get_ddl('SEQUENCE', :name, :owner) from dual",
                {"owner": safe_owner, "name": safe_sequence_name},
            )
            ddl_row = cursor.fetchone()
            sequence_ddl = str(ddl_row[0]).strip().rstrip(";") if ddl_row and ddl_row[0] else ""
            if not sequence_ddl:
                raise ValueError(f"Could not obtain DDL for sequence {safe_owner}.{safe_sequence_name}.")
            sequence_ddl, start_replacements = re.subn(
                r"(?im)^\s*START\s+WITH\s+\d+\s*$",
                f"  START WITH {next_value}",
                sequence_ddl,
            )
            if start_replacements != 1:
                raise ValueError("Sequence DDL did not contain exactly one START WITH clause.")
            sequence_ddl, cache_replacements = re.subn(
                r"(?im)^\s*(?:CACHE\s+\d+|NOCACHE)\s*$",
                "  NOCACHE",
                sequence_ddl,
            )
            if cache_replacements == 0:
                sequence_ddl = f"{sequence_ddl}\n  NOCACHE"
            elif cache_replacements != 1:
                raise ValueError("Sequence DDL contained multiple cache clauses.")

            cursor.execute(f"drop sequence {safe_owner}.{safe_sequence_name}")
            cursor.execute(sequence_ddl)
            cursor.execute(
                "select distinct o.owner, o.object_name, o.object_type "
                "from dba_dependencies d join dba_objects o "
                "on o.owner = d.owner and o.object_name = d.name and o.object_type = d.type "
                "where d.referenced_owner = :owner and d.referenced_name = :name and d.referenced_type = 'SEQUENCE' "
                "and o.status = 'INVALID' and o.object_type in "
                "('FUNCTION', 'PACKAGE', 'PACKAGE BODY', 'PROCEDURE', 'TRIGGER', 'TYPE', 'TYPE BODY', 'VIEW') "
                "order by o.owner, o.object_type, o.object_name",
                {"owner": safe_owner, "name": safe_sequence_name},
            )
            dependents = [(str(dep_owner), str(dep_name), str(dep_type)) for dep_owner, dep_name, dep_type in cursor]
            recompiled: list[dict[str, str]] = []
            compilation_errors: list[dict[str, str]] = []
            for dependent_owner, dependent_name, dependent_type in dependents:
                if dependent_type == "PACKAGE BODY":
                    compile_sql = f"alter package {dependent_owner}.{dependent_name} compile body"
                elif dependent_type == "TYPE BODY":
                    compile_sql = f"alter type {dependent_owner}.{dependent_name} compile body"
                else:
                    compile_sql = f"alter {dependent_type.lower()} {dependent_owner}.{dependent_name} compile"
                try:
                    cursor.execute(compile_sql)
                    recompiled.append({"owner": dependent_owner, "name": dependent_name, "type": dependent_type})
                except oracledb.DatabaseError as exc:
                    compilation_errors.append(
                        {"owner": dependent_owner, "name": dependent_name, "type": dependent_type, "error": str(exc)}
                    )
        return {
            "connection": connection_name,
            "owner": safe_owner,
            "sequence_name": safe_sequence_name,
            "start_with": next_value,
            "cache_setting": "NOCACHE",
            "recompiled_dependents": recompiled,
            "compilation_errors": compilation_errors,
        }
    finally:
        connection.close()

def search_saved_oracle_source(
    connection_name: str, search_terms: list[str], max_rows: int = 100
) -> dict[str, object]:
    """Search saved Oracle procedure, function, package, and trigger source.

    Every supplied term must occur in a returned source line.  The search is
    read-only, case-insensitive, capped at 500 rows, and never returns
    credentials.
    """
    if not isinstance(search_terms, list) or not 1 <= len(search_terms) <= 3:
        raise ValueError("Provide between one and three source search terms.")
    terms = [str(term).strip().upper() for term in search_terms]
    if any(not term for term in terms):
        raise ValueError("Source search terms must not be empty.")
    row_limit = max(1, min(int(max_rows), 500))
    predicates = " and ".join(
        f"upper(s.text) like :term{index}" for index in range(len(terms))
    )
    binds = {f"term{index}": f"%{term}%" for index, term in enumerate(terms)}
    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select s.owner, s.name, s.type, s.line, rtrim(s.text) "
                "from dba_source s "
                "where s.type in ('PROCEDURE', 'FUNCTION', 'PACKAGE', 'PACKAGE BODY', 'TRIGGER') and "
                f"{predicates} "
                "order by s.owner, s.name, s.type, s.line",
                binds,
            )
            matches = [
                {
                    "owner": str(owner),
                    "name": str(name),
                    "type": str(source_type),
                    "line": int(line),
                    "text": str(text) if text else "",
                }
                for owner, name, source_type, line, text in cursor.fetchmany(row_limit)
            ]
        return {
            "connection": connection_name,
            "search_terms": terms,
            "row_limit": row_limit,
            "matches": matches,
        }
    finally:
        connection.close()

def inspect_saved_table_sync_sources(
    connection_name: str, owner: str, table_name: str
) -> dict[str, object]:
    """Identify stored code and jobs that read or write a saved Oracle table.

    This read-only check finds source references, resolves their enclosing
    procedure or function, lists table triggers and dependencies, and
    correlates Scheduler and legacy jobs that invoke matching program units.
    It never returns credentials or table data.
    """
    safe_owner = str(owner).strip().upper()
    safe_table = str(table_name).strip().upper()
    identifier_pattern = r"[A-Z][A-Z0-9_$#]*"
    if not re.fullmatch(identifier_pattern, safe_owner):
        raise ValueError("owner must be a simple Oracle identifier.")
    if not re.fullmatch(identifier_pattern, safe_table):
        raise ValueError("table_name must be a simple Oracle identifier.")

    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select owner, name, type, line, rtrim(text) from dba_source "
                "where upper(text) like :needle "
                "order by owner, name, type, line",
                needle=f"%{safe_table}%",
            )
            raw_matches = list(cursor)
            source_objects = sorted(
                {(str(row[0]), str(row[1]), str(row[2])) for row in raw_matches}
            )
            source_by_object: dict[tuple[str, str, str], list[tuple[int, str]]] = {}
            for source_owner, source_name, source_type in source_objects:
                cursor.execute(
                    "select line, rtrim(text) from dba_source "
                    "where owner = :owner and name = :name and type = :type "
                    "order by line",
                    owner=source_owner,
                    name=source_name,
                    type=source_type,
                )
                source_by_object[(source_owner, source_name, source_type)] = [
                    (int(line), str(text or "")) for line, text in cursor
                ]

            references = []
            routine_pattern = re.compile(
                r"^\s*(?:procedure|function)\s+([A-Za-z][A-Za-z0-9_$#]*)",
                re.IGNORECASE,
            )
            for source_owner, source_name, source_type, line, text in raw_matches:
                enclosing_routine = None
                for prior_line, prior_text in source_by_object[
                    (str(source_owner), str(source_name), str(source_type))
                ]:
                    if prior_line > int(line):
                        break
                    routine_match = routine_pattern.match(prior_text)
                    if routine_match:
                        enclosing_routine = routine_match.group(1).upper()
                normalized_text = str(text or "").upper()
                operation = "REFERENCE"
                for keyword in ("MERGE", "INSERT", "UPDATE", "DELETE", "SELECT"):
                    if re.search(rf"\b{keyword}\b", normalized_text):
                        operation = keyword
                        break
                references.append(
                    {
                        "owner": str(source_owner),
                        "name": str(source_name),
                        "type": str(source_type),
                        "enclosing_routine": enclosing_routine,
                        "line": int(line),
                        "operation": operation,
                        "text": str(text or ""),
                    }
                )

            cursor.execute(
                "select owner, trigger_name, status, trigger_type, triggering_event "
                "from dba_triggers where table_owner = :owner and table_name = :table_name "
                "order by owner, trigger_name",
                owner=safe_owner,
                table_name=safe_table,
            )
            triggers = [
                {
                    "owner": str(trigger_owner),
                    "trigger_name": str(trigger_name),
                    "status": str(status),
                    "trigger_type": str(trigger_type),
                    "triggering_event": str(triggering_event),
                }
                for trigger_owner, trigger_name, status, trigger_type, triggering_event in cursor
            ]

            cursor.execute(
                "select owner, name, type from dba_dependencies "
                "where referenced_owner = :owner and referenced_name = :table_name "
                "order by owner, name, type",
                owner=safe_owner,
                table_name=safe_table,
            )
            dependencies = [
                {"owner": str(dep_owner), "name": str(name), "type": str(dep_type)}
                for dep_owner, name, dep_type in cursor
            ]

            callable_names = {safe_table}
            callable_names.update(name.upper() for _, name, _ in source_objects)
            callable_names.update(
                str(reference["enclosing_routine"]).upper()
                for reference in references
                if reference["enclosing_routine"]
            )
            cursor.execute(
                "select j.owner, j.job_name, j.enabled, j.state, j.job_type, "
                "j.job_action, j.program_owner, j.program_name, p.program_action, "
                "j.repeat_interval from dba_scheduler_jobs j "
                "left join dba_scheduler_programs p on p.owner = j.program_owner "
                "and p.program_name = j.program_name "
                "order by j.owner, j.job_name"
            )
            scheduler_jobs = []
            for row in cursor:
                searchable = " ".join(str(value or "") for value in row[5:9]).upper()
                matched_names = sorted(name for name in callable_names if name in searchable)
                if matched_names:
                    scheduler_jobs.append(
                        {
                            "owner": str(row[0]),
                            "job_name": str(row[1]),
                            "enabled": bool(row[2]),
                            "state": str(row[3]),
                            "job_type": str(row[4]),
                            "job_action": str(row[5]) if row[5] else None,
                            "program_owner": str(row[6]) if row[6] else None,
                            "program_name": str(row[7]) if row[7] else None,
                            "program_action": str(row[8]) if row[8] else None,
                            "repeat_interval": str(row[9]) if row[9] else None,
                            "matched_names": matched_names,
                        }
                    )

            cursor.execute("select job, schema_user, what, broken, interval from dba_jobs order by job")
            legacy_jobs = []
            for job, schema_user, what, broken, interval in cursor:
                searchable = str(what or "").upper()
                matched_names = sorted(name for name in callable_names if name in searchable)
                if matched_names:
                    legacy_jobs.append(
                        {
                            "job": int(job),
                            "schema_user": str(schema_user),
                            "what": str(what),
                            "broken": str(broken),
                            "interval": str(interval) if interval else None,
                            "matched_names": matched_names,
                        }
                    )

            cursor.execute(
                "select q.sql_id, q.parsing_schema_name, q.module, q.action, "
                "c.command_name, q.executions, "
                "to_char(q.last_active_time, 'YYYY-MM-DD HH24:MI:SS') "
                "from v$sql q left join v$sqlcommand c on c.command_type = q.command_type "
                "where q.command_type in (2, 6, 7, 189) "
                "and upper(q.sql_text) like :needle "
                "order by q.last_active_time desc nulls last",
                needle=f"%{safe_table}%",
            )
            recent_dml = [
                {
                    "sql_id": str(sql_id),
                    "parsing_schema": str(parsing_schema) if parsing_schema else None,
                    "module": str(module) if module else None,
                    "action": str(action) if action else None,
                    "command": str(command_name) if command_name else None,
                    "executions": int(executions),
                    "last_active_time": str(last_active_time) if last_active_time else None,
                }
                for sql_id, parsing_schema, module, action, command_name, executions,
                last_active_time in cursor
            ]

        return {
            "connection": connection_name,
            "owner": safe_owner,
            "table_name": safe_table,
            "source_references": references,
            "triggers": triggers,
            "dependencies": dependencies,
            "scheduler_jobs": scheduler_jobs,
            "legacy_jobs": legacy_jobs,
            "recent_dml": recent_dml,
        }
    finally:
        connection.close()

def inspect_saved_table_statistics(
    connection_name: str, tables: list[dict[str, str]]
) -> dict[str, object]:
    """Return optimizer row-count statistics for explicitly named saved Oracle tables.

    This read-only check reads ``DBA_TABLES.NUM_ROWS`` and ``LAST_ANALYZED``;
    it avoids running potentially expensive full-table ``COUNT(*)`` scans on a
    production database.  ``NUM_ROWS`` is an estimate from the latest
    statistics collection and may be stale.
    """
    if not isinstance(tables, list) or not 1 <= len(tables) <= 25:
        raise ValueError("tables must contain between 1 and 25 owner/table entries.")
    identifier_pattern = r"[A-Z][A-Z0-9_$#]*"
    normalized: list[tuple[str, str]] = []
    for item in tables:
        if not isinstance(item, dict):
            raise ValueError("Each table entry must be an object with owner and table_name.")
        owner = str(item.get("owner", "")).strip().upper()
        table_name = str(item.get("table_name", "")).strip().upper()
        if not re.fullmatch(identifier_pattern, owner) or not re.fullmatch(identifier_pattern, table_name):
            raise ValueError("owner and table_name must be simple Oracle identifiers.")
        normalized.append((owner, table_name))

    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            results: list[dict[str, object]] = []
            for owner, table_name in normalized:
                cursor.execute(
                    "select num_rows, last_analyzed, stale_stats from dba_tab_statistics "
                    "where owner = :owner and table_name = :table_name and partition_name is null",
                    {"owner": owner, "table_name": table_name},
                )
                row = cursor.fetchone()
                if row is None:
                    results.append({"owner": owner, "table_name": table_name, "found": False})
                    continue
                num_rows, last_analyzed, stale_stats = row
                results.append({
                    "owner": owner,
                    "table_name": table_name,
                    "found": True,
                    "estimated_row_count": int(num_rows) if num_rows is not None else None,
                    "last_analyzed": str(last_analyzed) if last_analyzed else None,
                    "stale_stats": str(stale_stats) if stale_stats else None,
                })
        return {"connection": connection_name, "tables": results}
    finally:
        connection.close()

def gather_saved_table_statistics(
    connection_name: str, tables: list[dict[str, str]], confirmed: bool = False
) -> dict[str, object]:
    """Gather Oracle optimizer and index statistics for explicit tables.

    This is a database maintenance operation.  It uses ``AUTO_SAMPLE_SIZE``
    and gathers dependent index statistics, one table at a time.  It requires
    explicit confirmation because it can consume database resources.
    """
    if confirmed is not True:
        raise ValueError("Set confirmed=true only after explicit approval to gather table statistics.")
    if not isinstance(tables, list) or not 1 <= len(tables) <= 25:
        raise ValueError("tables must contain between 1 and 25 owner/table entries.")
    identifier_pattern = r"[A-Z][A-Z0-9_$#]*"
    normalized: list[tuple[str, str]] = []
    for item in tables:
        if not isinstance(item, dict):
            raise ValueError("Each table entry must be an object with owner and table_name.")
        owner = str(item.get("owner", "")).strip().upper()
        table_name = str(item.get("table_name", "")).strip().upper()
        if not re.fullmatch(identifier_pattern, owner) or not re.fullmatch(identifier_pattern, table_name):
            raise ValueError("owner and table_name must be simple Oracle identifiers.")
        normalized.append((owner, table_name))

    connection = _connect_saved_oracle(connection_name)
    try:
        results: list[dict[str, object]] = []
        with connection.cursor() as cursor:
            for owner, table_name in normalized:
                try:
                    cursor.execute(
                        "begin dbms_stats.gather_table_stats("
                        "ownname => :owner, tabname => :table_name, "
                        "estimate_percent => dbms_stats.auto_sample_size, "
                        "method_opt => 'FOR ALL COLUMNS SIZE AUTO', cascade => true); end;",
                        {"owner": owner, "table_name": table_name},
                    )
                    cursor.execute(
                        "select num_rows, last_analyzed, stale_stats from dba_tab_statistics "
                        "where owner = :owner and table_name = :table_name and partition_name is null",
                        {"owner": owner, "table_name": table_name},
                    )
                    row = cursor.fetchone()
                    num_rows, last_analyzed, stale_stats = row if row else (None, None, None)
                    results.append({
                        "owner": owner,
                        "table_name": table_name,
                        "status": "gathered",
                        "estimated_row_count": int(num_rows) if num_rows is not None else None,
                        "last_analyzed": str(last_analyzed) if last_analyzed else None,
                        "stale_stats": str(stale_stats) if stale_stats else None,
                    })
                except oracledb.DatabaseError as exc:
                    results.append({"owner": owner, "table_name": table_name, "status": "failed", "error": str(exc)})
        return {"connection": connection_name, "tables": results}
    finally:
        connection.close()

def compare_saved_table_statistics_to_counts(
    connection_name: str, tables: list[dict[str, str]]
) -> dict[str, object]:
    """Compare optimizer row estimates with exact ``COUNT(*)`` results.

    This read-only operation counts each explicitly named table sequentially.
    Exact counts can be resource-intensive on large production tables.
    """
    if not isinstance(tables, list) or not 1 <= len(tables) <= 25:
        raise ValueError("tables must contain between 1 and 25 owner/table entries.")
    identifier_pattern = r"[A-Z][A-Z0-9_$#]*"
    normalized: list[tuple[str, str]] = []
    for item in tables:
        if not isinstance(item, dict):
            raise ValueError("Each table entry must be an object with owner and table_name.")
        owner = str(item.get("owner", "")).strip().upper()
        table_name = str(item.get("table_name", "")).strip().upper()
        if not re.fullmatch(identifier_pattern, owner) or not re.fullmatch(identifier_pattern, table_name):
            raise ValueError("owner and table_name must be simple Oracle identifiers.")
        normalized.append((owner, table_name))

    connection = _connect_saved_oracle(connection_name)
    try:
        results: list[dict[str, object]] = []
        with connection.cursor() as cursor:
            for owner, table_name in normalized:
                cursor.execute(
                    "select num_rows, last_analyzed, stale_stats from dba_tab_statistics "
                    "where owner = :owner and table_name = :table_name and partition_name is null",
                    {"owner": owner, "table_name": table_name},
                )
                stat_row = cursor.fetchone()
                estimated_rows, last_analyzed, stale_stats = stat_row if stat_row else (None, None, None)
                cursor.execute(f"select count(*) from {owner}.{table_name}")
                actual_rows = int(cursor.fetchone()[0])
                results.append({
                    "owner": owner,
                    "table_name": table_name,
                    "estimated_row_count": int(estimated_rows) if estimated_rows is not None else None,
                    "actual_row_count": actual_rows,
                    "difference": actual_rows - int(estimated_rows) if estimated_rows is not None else None,
                    "last_analyzed": str(last_analyzed) if last_analyzed else None,
                    "stale_stats": str(stale_stats) if stale_stats else None,
                })
        return {"connection": connection_name, "tables": results}
    finally:
        connection.close()

def inspect_saved_open_sessions(connection_name: str) -> dict[str, object]:
    """List currently open user sessions on a saved Oracle connection.

    This read-only check uses only a matching Windows Credential Manager entry.
    It excludes Oracle background sessions and never returns credentials or SQL
    text.
    """
    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select s.sid, s.serial#, s.username, s.status, s.osuser, s.machine, "
                "s.program, s.module, s.action, s.sql_id, "
                "to_char(s.logon_time, 'YYYY-MM-DD HH24:MI:SS'), s.event, s.wait_class "
                "from v$session s "
                "where s.type = 'USER' "
                "order by case s.status when 'ACTIVE' then 0 else 1 end, s.logon_time, s.sid"
            )
            sessions = [
                {
                    "sid": int(sid),
                    "serial": int(serial),
                    "username": str(username) if username else None,
                    "status": str(status),
                    "osuser": str(osuser) if osuser else None,
                    "machine": str(machine) if machine else None,
                    "program": str(program) if program else None,
                    "module": str(module) if module else None,
                    "action": str(action) if action else None,
                    "sql_id": str(sql_id) if sql_id else None,
                    "logon_time": str(logon_time),
                    "event": str(event) if event else None,
                    "wait_class": str(wait_class) if wait_class else None,
                }
                for sid, serial, username, status, osuser, machine, program, module,
                action, sql_id, logon_time, event, wait_class in cursor
            ]
        return {"connection": connection_name, "sessions": sessions}
    finally:
        connection.close()

def inspect_saved_oracle_locks(connection_name: str) -> dict[str, object]:
    """Inspect current Oracle lock waiters, blockers, and locked objects.

    This read-only check uses ``GV$LOCK`` for waiter-to-holder pairs and
    ``GV$LOCKED_OBJECT`` for schema objects held by active or inactive user
    sessions. It never returns credentials or SQL text.
    """
    lock_modes = {
        0: "None",
        1: "Null",
        2: "Row-S (SS)",
        3: "Row-X (SX)",
        4: "Share",
        5: "S/Row-X (SSX)",
        6: "Exclusive",
    }
    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select w.inst_id, w.sid, ws.serial#, ws.username, ws.status, "
                "ws.osuser, ws.machine, ws.program, ws.module, ws.sql_id, "
                "ws.event, ws.wait_class, ws.seconds_in_wait, "
                "h.inst_id, h.sid, bs.serial#, bs.username, bs.status, "
                "bs.osuser, bs.machine, bs.program, bs.module, bs.sql_id, "
                "w.type, h.lmode, w.request, w.id1, w.id2 "
                "from gv$lock w "
                "join gv$lock h on h.type = w.type and h.id1 = w.id1 and h.id2 = w.id2 "
                "and h.lmode > 0 and (h.inst_id <> w.inst_id or h.sid <> w.sid) "
                "left join gv$session ws on ws.inst_id = w.inst_id and ws.sid = w.sid "
                "left join gv$session bs on bs.inst_id = h.inst_id and bs.sid = h.sid "
                "where w.request > 0 "
                "order by ws.seconds_in_wait desc nulls last, w.inst_id, w.sid"
            )
            blocking_pairs = [
                {
                    "waiter_instance": int(waiter_instance),
                    "waiter_sid": int(waiter_sid),
                    "waiter_serial": int(waiter_serial) if waiter_serial is not None else None,
                    "waiter_username": str(waiter_username) if waiter_username else None,
                    "waiter_status": str(waiter_status) if waiter_status else None,
                    "waiter_osuser": str(waiter_osuser) if waiter_osuser else None,
                    "waiter_machine": str(waiter_machine) if waiter_machine else None,
                    "waiter_program": str(waiter_program) if waiter_program else None,
                    "waiter_module": str(waiter_module) if waiter_module else None,
                    "waiter_sql_id": str(waiter_sql_id) if waiter_sql_id else None,
                    "wait_event": str(wait_event) if wait_event else None,
                    "wait_class": str(wait_class) if wait_class else None,
                    "seconds_in_wait": int(seconds_in_wait) if seconds_in_wait is not None else None,
                    "blocker_instance": int(blocker_instance),
                    "blocker_sid": int(blocker_sid),
                    "blocker_serial": int(blocker_serial) if blocker_serial is not None else None,
                    "blocker_username": str(blocker_username) if blocker_username else None,
                    "blocker_status": str(blocker_status) if blocker_status else None,
                    "blocker_osuser": str(blocker_osuser) if blocker_osuser else None,
                    "blocker_machine": str(blocker_machine) if blocker_machine else None,
                    "blocker_program": str(blocker_program) if blocker_program else None,
                    "blocker_module": str(blocker_module) if blocker_module else None,
                    "blocker_sql_id": str(blocker_sql_id) if blocker_sql_id else None,
                    "lock_type": str(lock_type),
                    "held_mode": lock_modes.get(int(held_mode), str(held_mode)),
                    "requested_mode": lock_modes.get(int(requested_mode), str(requested_mode)),
                    "lock_id1": int(lock_id1),
                    "lock_id2": int(lock_id2),
                }
                for waiter_instance, waiter_sid, waiter_serial, waiter_username,
                waiter_status, waiter_osuser, waiter_machine, waiter_program,
                waiter_module, waiter_sql_id, wait_event, wait_class, seconds_in_wait,
                blocker_instance, blocker_sid, blocker_serial, blocker_username,
                blocker_status, blocker_osuser, blocker_machine, blocker_program,
                blocker_module, blocker_sql_id, lock_type, held_mode, requested_mode,
                lock_id1, lock_id2 in cursor
            ]
            cursor.execute(
                "select lo.inst_id, lo.session_id, s.serial#, s.username, s.status, "
                "s.osuser, s.machine, s.program, s.module, s.sql_id, s.event, "
                "s.wait_class, s.seconds_in_wait, lo.locked_mode, o.owner, "
                "o.object_name, o.object_type "
                "from gv$locked_object lo "
                "left join gv$session s on s.inst_id = lo.inst_id and s.sid = lo.session_id "
                "left join dba_objects o on o.object_id = lo.object_id "
                "order by o.owner, o.object_name, lo.inst_id, lo.session_id"
            )
            locked_objects = [
                {
                    "instance": int(instance),
                    "sid": int(sid),
                    "serial": int(serial) if serial is not None else None,
                    "username": str(username) if username else None,
                    "status": str(status) if status else None,
                    "osuser": str(osuser) if osuser else None,
                    "machine": str(machine) if machine else None,
                    "program": str(program) if program else None,
                    "module": str(module) if module else None,
                    "sql_id": str(sql_id) if sql_id else None,
                    "event": str(event) if event else None,
                    "wait_class": str(wait_class) if wait_class else None,
                    "seconds_in_wait": int(seconds_in_wait) if seconds_in_wait is not None else None,
                    "locked_mode": lock_modes.get(int(locked_mode), str(locked_mode)),
                    "object_owner": str(object_owner) if object_owner else None,
                    "object_name": str(object_name) if object_name else None,
                    "object_type": str(object_type) if object_type else None,
                }
                for instance, sid, serial, username, status, osuser, machine,
                program, module, sql_id, event, wait_class, seconds_in_wait,
                locked_mode, object_owner, object_name, object_type in cursor
            ]
        return {
            "connection": connection_name,
            "blocking_pair_count": len(blocking_pairs),
            "blocking_pairs": blocking_pairs,
            "locked_object_count": len(locked_objects),
            "locked_objects": locked_objects,
        }
    finally:
        connection.close()

def inspect_saved_oracle_diagnostics(connection_name: str) -> dict[str, object]:
    """Return Oracle ADR and alert-log locations for a saved connection.

    This read-only check queries ``V$DIAG_INFO``, ``V$INSTANCE``, and the
    ``diagnostic_dest`` parameter. It also returns the database startup time
    and calculated uptime. It does not read diagnostic files and never returns
    credentials.
    """
    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select instance_name, host_name, startup_time, "
                "trunc((sysdate - startup_time) * 86400) "
                "from v$instance"
            )
            instance_name, host_name, startup_time, uptime_seconds = cursor.fetchone()
            cursor.execute(
                "select name, value from v$diag_info "
                "where name in ('ADR Base', 'ADR Home', 'Diag Trace', "
                "'Diag Alert', 'Default Trace File') order by name"
            )
            diagnostic_info = {str(name): str(value) for name, value in cursor}
            cursor.execute("select value from v$parameter where name = 'diagnostic_dest'")
            diagnostic_dest_row = cursor.fetchone()
        trace_directory = diagnostic_info.get("Diag Trace")
        alert_log = None
        if trace_directory:
            separator = "\\" if "\\" in trace_directory else "/"
            alert_log = (
                trace_directory.rstrip("\\/")
                + separator
                + f"alert_{str(instance_name).lower()}.log"
            )
        uptime_seconds = int(uptime_seconds)
        uptime_days, remainder = divmod(uptime_seconds, 86400)
        uptime_hours, remainder = divmod(remainder, 3600)
        uptime_minutes, uptime_seconds_remainder = divmod(remainder, 60)
        return {
            "connection": connection_name,
            "instance_name": str(instance_name),
            "host_name": str(host_name),
            "startup_time": (
                startup_time.isoformat(sep=" ")
                if hasattr(startup_time, "isoformat")
                else str(startup_time)
            ),
            "uptime_seconds": int(
                (uptime_days * 86400)
                + (uptime_hours * 3600)
                + (uptime_minutes * 60)
                + uptime_seconds_remainder
            ),
            "uptime": (
                f"{uptime_days}d {uptime_hours:02d}h "
                f"{uptime_minutes:02d}m {uptime_seconds_remainder:02d}s"
            ),
            "diagnostic_dest": (
                str(diagnostic_dest_row[0]) if diagnostic_dest_row else None
            ),
            "adr_base": diagnostic_info.get("ADR Base"),
            "adr_home": diagnostic_info.get("ADR Home"),
            "diag_trace": trace_directory,
            "diag_alert": diagnostic_info.get("Diag Alert"),
            "default_trace_file": diagnostic_info.get("Default Trace File"),
            "text_alert_log": alert_log,
        }
    finally:
        connection.close()

def inspect_saved_session_count(connection_name: str) -> dict[str, object]:
    """Return ``SELECT COUNT(*) FROM V$SESSION`` for a saved Oracle connection.

    This read-only check uses only a matching Windows Credential Manager entry.
    It counts every row in ``V$SESSION``, including Oracle background and the
    MCP query session, and never returns credentials.
    """
    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute("select count(*) from v$session")
            (session_count,) = cursor.fetchone()
        return {"connection": connection_name, "session_count": int(session_count)}
    finally:
        connection.close()

def inspect_saved_session_users(connection_name: str) -> dict[str, object]:
    """List distinct authenticated usernames from ``V$SESSION`` on a saved connection.

    This read-only check uses only a matching Windows Credential Manager entry.
    Oracle background processes without a username are excluded, and no
    credentials or SQL text are returned.
    """
    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select distinct username from v$session "
                "where username is not null order by username"
            )
            usernames = [str(username) for (username,) in cursor]
        return {"connection": connection_name, "usernames": usernames}
    finally:
        connection.close()

def inspect_saved_routine_callers(
    connection_name: str, owner: str, routine_name: str
) -> dict[str, object]:
    """Find stored-code and Scheduler callers of one saved Oracle routine.

    This read-only check searches ``DBA_SOURCE``, ``DBA_SCHEDULER_JOBS`` and
    their program actions, plus legacy ``DBA_JOBS``. It finds static textual
    calls to the supplied fully-qualified ``owner.routine_name``; dynamic SQL
    and external application calls cannot be proven absent.
    """
    safe_owner = str(owner).strip().upper()
    safe_routine = str(routine_name).strip().upper()
    identifier_pattern = r"[A-Z][A-Z0-9_$#]{0,29}"
    if not re.fullmatch(identifier_pattern, safe_owner):
        raise ValueError("owner must be a simple Oracle identifier.")
    if not re.fullmatch(identifier_pattern, safe_routine):
        raise ValueError("routine_name must be a simple Oracle identifier.")
    qualified_name = f"{safe_owner}.{safe_routine}"
    needle = f"%{qualified_name}%"

    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select owner, name, type, line, rtrim(text) from dba_source "
                "where upper(text) like :needle order by owner, name, type, line",
                {"needle": needle},
            )
            source_callers = [
                {
                    "owner": str(source_owner),
                    "name": str(name),
                    "type": str(object_type),
                    "line": int(line),
                    "text": str(text or ""),
                }
                for source_owner, name, object_type, line, text in cursor
            ]
            cursor.execute(
                "select j.owner, j.job_name, j.job_type, j.job_action, j.program_owner, j.program_name, "
                "j.enabled, j.state, p.program_action "
                "from dba_scheduler_jobs j left join dba_scheduler_programs p "
                "on p.owner = j.program_owner and p.program_name = j.program_name "
                "where upper(nvl(j.job_action, ' ')) like :needle "
                "or upper(nvl(p.program_action, ' ')) like :needle "
                "order by j.owner, j.job_name",
                {"needle": needle},
            )
            scheduler_callers = [
                {
                    "owner": str(job_owner),
                    "job_name": str(job_name),
                    "job_type": str(job_type),
                    "job_action": str(job_action) if job_action else None,
                    "program_owner": str(program_owner) if program_owner else None,
                    "program_name": str(program_name) if program_name else None,
                    "enabled": str(enabled),
                    "state": str(state),
                    "program_action": str(program_action) if program_action else None,
                }
                for job_owner, job_name, job_type, job_action, program_owner, program_name,
                enabled, state, program_action in cursor
            ]
            cursor.execute(
                "select job, schema_user, what, broken from dba_jobs "
                "where upper(nvl(what, ' ')) like :needle order by job",
                {"needle": needle},
            )
            legacy_job_callers = [
                {
                    "job": int(job),
                    "schema_user": str(schema_user),
                    "what": str(what or ""),
                    "broken": str(broken),
                }
                for job, schema_user, what, broken in cursor
            ]
        return {
            "connection": connection_name,
            "owner": safe_owner,
            "routine_name": safe_routine,
            "source_callers": source_callers,
            "scheduler_callers": scheduler_callers,
            "legacy_job_callers": legacy_job_callers,
        }
    finally:
        connection.close()

def export_saved_oracle_object(
    connection_name: str, owner: str, object_name: str, object_type: str
) -> dict[str, object]:
    """Export one saved Oracle object DDL and its direct dependency metadata.

    This read-only check obtains the current DDL with ``DBMS_METADATA`` and
    lists direct referenced objects and direct dependents from
    ``DBA_DEPENDENCIES``. It does not export data or credentials.
    """
    safe_owner = str(owner).strip().upper()
    safe_name = str(object_name).strip().upper()
    safe_type = str(object_type).strip().upper().replace("_", " ")
    identifier_pattern = r"[A-Z][A-Z0-9_$#]{0,29}"
    allowed_types = {"PROCEDURE", "FUNCTION", "PACKAGE", "PACKAGE BODY", "TRIGGER", "TYPE", "TYPE BODY", "VIEW", "MATERIALIZED VIEW", "TABLE", "SEQUENCE"}
    if not re.fullmatch(identifier_pattern, safe_owner) or not re.fullmatch(identifier_pattern, safe_name):
        raise ValueError("owner and object_name must be simple Oracle identifiers.")
    if safe_type not in allowed_types:
        raise ValueError(f"object_type must be one of: {', '.join(sorted(allowed_types))}.")

    metadata_type = safe_type.replace(" ", "_")
    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select status from dba_objects where owner = :owner and object_name = :name and object_type = :type",
                {"owner": safe_owner, "name": safe_name, "type": safe_type},
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError(f"Object {safe_owner}.{safe_name} ({safe_type}) was not found.")
            cursor.execute(
                "select dbms_metadata.get_ddl(:metadata_type, :name, :owner) from dual",
                {"metadata_type": metadata_type, "name": safe_name, "owner": safe_owner},
            )
            ddl_row = cursor.fetchone()
            ddl = str(ddl_row[0]) if ddl_row and ddl_row[0] is not None else ""
            if not ddl:
                raise ValueError(f"Could not retrieve DDL for {safe_owner}.{safe_name} ({safe_type}).")
            cursor.execute(
                "select referenced_owner, referenced_name, referenced_type, dependency_type "
                "from dba_dependencies where owner = :owner and name = :name and type = :type "
                "order by referenced_owner, referenced_type, referenced_name",
                {"owner": safe_owner, "name": safe_name, "type": safe_type},
            )
            dependencies = [
                {"owner": str(dep_owner), "name": str(dep_name), "type": str(dep_type), "dependency_type": str(dep_kind)}
                for dep_owner, dep_name, dep_type, dep_kind in cursor
            ]
            cursor.execute(
                "select owner, name, type, dependency_type from dba_dependencies "
                "where referenced_owner = :owner and referenced_name = :name and referenced_type = :type "
                "order by owner, type, name",
                {"owner": safe_owner, "name": safe_name, "type": safe_type},
            )
            dependents = [
                {"owner": str(dep_owner), "name": str(dep_name), "type": str(dep_type), "dependency_type": str(dep_kind)}
                for dep_owner, dep_name, dep_type, dep_kind in cursor
            ]
        return {
            "connection": connection_name,
            "owner": safe_owner,
            "object_name": safe_name,
            "object_type": safe_type,
            "status": str(row[0]),
            "ddl": ddl,
            "dependencies": dependencies,
            "dependents": dependents,
        }
    finally:
        connection.close()

def inspect_saved_sys_session_sql(connection_name: str) -> dict[str, object]:
    """List ``SYS`` user sessions and their current SQL text.

    This read-only check uses only a matching Windows Credential Manager entry.
    Oracle background processes are excluded.
    """
    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select s.sid, s.serial#, s.status, s.osuser, s.machine, s.program, "
                "s.module, s.sql_id, q.sql_fulltext "
                "from v$session s "
                "left join v$sql q on q.sql_id = s.sql_id and q.child_number = s.sql_child_number "
                "where s.type = 'USER' and s.username = 'SYS' "
                "order by case s.status when 'ACTIVE' then 0 else 1 end, s.sid"
            )
            sessions = [
                {
                    "sid": int(sid),
                    "serial": int(serial),
                    "status": str(status),
                    "osuser": str(osuser) if osuser else None,
                    "machine": str(machine) if machine else None,
                    "program": str(program) if program else None,
                    "module": str(module) if module else None,
                    "sql_id": str(sql_id) if sql_id else None,
                    "sql_text": str(sql_text) if sql_text else None,
                }
                for sid, serial, status, osuser, machine, program, module, sql_id, sql_text in cursor
            ]
        return {"connection": connection_name, "sessions": sessions}
    finally:
        connection.close()

def inspect_saved_top_pga_consumers(connection_name: str, limit: int = 20) -> dict[str, object]:
    """List current Oracle user sessions with the largest allocated PGA memory.

    This read-only operation joins ``V$SESSION`` and ``V$PROCESS`` and returns
    current allocation, use, peak PGA, SQL identity, and module context.
    """
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100.")
    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select * from ("
                "select s.sid, s.serial#, s.username, s.status, s.module, s.action, s.sql_id, "
                "s.event, p.spid, p.pga_used_mem, p.pga_alloc_mem, p.pga_max_mem "
                "from v$session s join v$process p on p.addr = s.paddr "
                "where s.type = 'USER' order by p.pga_alloc_mem desc nulls last"
                ") where rownum <= :limit",
                {"limit": limit},
            )
            sessions = [
                {
                    "sid": int(sid), "serial": int(serial), "username": str(username) if username else None,
                    "status": str(status), "module": str(module) if module else None,
                    "action": str(action) if action else None, "sql_id": str(sql_id) if sql_id else None,
                    "event": str(event) if event else None, "server_process_id": str(spid) if spid else None,
                    "pga_used_bytes": int(used or 0), "pga_allocated_bytes": int(allocated or 0),
                    "pga_max_bytes": int(maximum or 0),
                }
                for sid, serial, username, status, module, action, sql_id, event, spid, used, allocated, maximum in cursor
            ]
        return {"connection": connection_name, "sessions": sessions}
    finally:
        connection.close()


@mcp.tool()
def inspect_saved_ash_client_attribution(
    connection_name: str,
    start_time: str,
    end_time: str,
    limit: int = 20,
) -> dict[str, object]:
    """Attribute historical foreground activity to users and client machines.

    The read-only report groups ASH samples by Oracle user, machine, program,
    module, action, and SQL ID. ``start_time`` and ``end_time`` must be ISO
    timestamps; the interval is limited to seven days and ``limit`` is capped
    at 100 rows. ASH is sampled activity, so counts indicate observed activity
    rather than an exact session-creation count.
    """
    try:
        start = datetime.fromisoformat(start_time.strip().replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_time.strip().replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("start_time and end_time must be ISO timestamps.") from exc
    if start.tzinfo is not None:
        start = start.astimezone(timezone.utc).replace(tzinfo=None)
    if end.tzinfo is not None:
        end = end.astimezone(timezone.utc).replace(tzinfo=None)
    if end <= start:
        raise ValueError("end_time must be later than start_time.")
    if end - start > timedelta(days=7):
        raise ValueError("The ASH interval cannot exceed seven days.")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100.")

    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select count(*), min(sample_time), max(sample_time) "
                "from dba_hist_active_sess_history"
            )
            total_samples, earliest_sample, latest_sample = cursor.fetchone()
            cursor.execute(
                "select session_type, count(*) from dba_hist_active_sess_history "
                "group by session_type order by session_type"
            )
            session_type_counts = {
                str(session_type) if session_type else "(null)": int(count)
                for session_type, count in cursor
            }
            cursor.execute(
                "select * from ("
                "select u.username, h.machine, h.program, h.module, h.action, h.sql_id, "
                "count(*) sample_count, count(distinct h.session_id) session_count, "
                "min(h.sample_time) first_sample_time, max(h.sample_time) last_sample_time "
                "from dba_hist_active_sess_history h "
                "left join dba_users u on u.user_id = h.user_id "
                "where h.sample_time >= :start_time and h.sample_time < :end_time "
                "and h.session_type = 'FOREGROUND' "
                "group by u.username, h.machine, h.program, h.module, h.action, h.sql_id "
                "order by count(*) desc, count(distinct h.session_id) desc"
                ") where rownum <= :limit",
                {"start_time": start, "end_time": end, "limit": limit},
            )
            rows = _fetch_dicts(cursor)
        return {
            "connection": connection_name,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "ash_total_samples": int(total_samples or 0),
            "ash_earliest_sample_time": _json_value(earliest_sample),
            "ash_latest_sample_time": _json_value(latest_sample),
            "ash_session_type_counts": session_type_counts,
            "rows": rows,
            "note": "ASH sample counts represent observed active-session activity, not exact session creation counts.",
        }
    finally:
        connection.close()

def inspect_saved_table_indexes(
    connection_name: str, tables: list[dict[str, object]]
) -> dict[str, object]:
    """List index definitions for explicit saved Oracle tables.

    This read-only operation returns normal index metadata and ordered columns
    for one to 25 owner/table pairs. It does not gather statistics or alter DDL.
    """
    identifier = re.compile(r"[A-Za-z][A-Za-z0-9_$#]{0,127}")
    if not 1 <= len(tables) <= 25:
        raise ValueError("tables must contain between one and 25 owner/table entries.")
    normalized = []
    for table in tables:
        if not isinstance(table, dict):
            raise ValueError("Each tables entry must be an object.")
        owner = str(table.get("owner", "")).upper()
        name = str(table.get("table_name", "")).upper()
        if not identifier.fullmatch(owner) or not identifier.fullmatch(name):
            raise ValueError("Each owner and table_name must be simple Oracle identifiers.")
        normalized.append((owner, name))
    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            result_tables = []
            for owner, name in normalized:
                cursor.execute(
                    "select i.index_name, i.index_type, i.uniqueness, i.status, i.visibility, "
                    "listagg(c.column_name || case when c.descend = 'DESC' then ' DESC' else '' end, ', ') "
                    "within group (order by c.column_position) "
                    "from dba_indexes i join dba_ind_columns c "
                    "on c.index_owner = i.owner and c.index_name = i.index_name "
                    "where i.table_owner = :owner and i.table_name = :table_name "
                    "group by i.index_name, i.index_type, i.uniqueness, i.status, i.visibility "
                    "order by i.index_name",
                    {"owner": owner, "table_name": name},
                )
                indexes = [
                    {"index_name": str(index_name), "index_type": str(index_type),
                     "uniqueness": str(uniqueness), "status": str(status),
                     "visibility": str(visibility), "columns": str(columns)}
                    for index_name, index_type, uniqueness, status, visibility, columns in cursor
                ]
                result_tables.append({"owner": owner, "table_name": name, "indexes": indexes})
        return {"connection": connection_name, "tables": result_tables}
    finally:
        connection.close()

def set_saved_pga_aggregate_limit(
    connection_name: str, limit_gib: int, confirmed: bool
) -> dict[str, object]:
    """Set PGA_AGGREGATE_LIMIT immediately and persistently on a saved target.

    This is a persistent instance-memory change. It requires explicit
    confirmation and refuses a limit below twice the current PGA target.
    """
    if not confirmed:
        raise ValueError("confirmed must be true after explicit approval for this write operation.")
    if not 2 <= limit_gib <= 4096:
        raise ValueError("limit_gib must be between 2 and 4096.")
    requested_bytes = limit_gib * 1024 ** 3
    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute("select value from v$parameter where name = 'pga_aggregate_target'")
            target = int(cursor.fetchone()[0])
            if requested_bytes < target * 2:
                raise ValueError("PGA_AGGREGATE_LIMIT must be at least twice PGA_AGGREGATE_TARGET.")
            cursor.execute("select value from v$parameter where name = 'pga_aggregate_limit'")
            before = int(cursor.fetchone()[0])
            cursor.execute(f"alter system set pga_aggregate_limit = {limit_gib}G scope=both")
            cursor.execute("select value from v$parameter where name = 'pga_aggregate_limit'")
            after = int(cursor.fetchone()[0])
        return {
            "connection": connection_name,
            "before_bytes": before,
            "after_bytes": after,
            "limit_gib": limit_gib,
            "scope": "BOTH",
            "restart_required": False,
        }
    finally:
        connection.close()

def set_saved_pga_aggregate_target(
    connection_name: str, target_gib: int, confirmed: bool
) -> dict[str, object]:
    """Set PGA_AGGREGATE_TARGET immediately and persistently on a saved target.

    This is a persistent instance-memory change. It requires explicit
    confirmation, validates the requested target against the existing PGA hard
    limit, and uses ``SCOPE=BOTH`` without an instance restart.
    """
    if not confirmed:
        raise ValueError("confirmed must be true after explicit approval for this write operation.")
    if not 1 <= target_gib <= 4096:
        raise ValueError("target_gib must be between 1 and 4096.")
    requested_bytes = target_gib * 1024 ** 3
    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select value from v$parameter where name = 'pga_aggregate_target'"
            )
            before = int(cursor.fetchone()[0])
            cursor.execute(
                "select value from v$parameter where name = 'pga_aggregate_limit'"
            )
            limit = int(cursor.fetchone()[0])
            if limit > 0 and requested_bytes * 2 > limit:
                raise ValueError("PGA_AGGREGATE_TARGET cannot exceed 50 percent of PGA_AGGREGATE_LIMIT.")
            cursor.execute(
                f"alter system set pga_aggregate_target = {target_gib}G scope=both"
            )
            cursor.execute(
                "select value from v$parameter where name = 'pga_aggregate_target'"
            )
            after = int(cursor.fetchone()[0])
        return {
            "connection": connection_name,
            "before_bytes": before,
            "after_bytes": after,
            "target_gib": target_gib,
            "pga_aggregate_limit_bytes": limit,
            "scope": "BOTH",
            "restart_required": False,
        }
    finally:
        connection.close()

def inspect_saved_oracle_memory_configuration(connection_name: str) -> dict[str, object]:
    """Inspect memory, workarea, optimizer, parallel, and PGA-pressure settings.

    This read-only operation returns the instance settings relevant to hash joins
    and selected runtime PGA counters. It does not change parameters or sessions.
    """
    parameter_names = (
        "memory_target", "memory_max_target", "sga_target", "sga_max_size",
        "pga_aggregate_target", "pga_aggregate_limit", "workarea_size_policy",
        "hash_area_size", "hash_join_multiblock_io_count", "db_block_size",
        "processes", "sessions", "parallel_max_servers", "parallel_degree_policy",
        "parallel_degree_limit", "optimizer_mode", "optimizer_features_enable",
        "cursor_sharing", "statistics_level", "resource_manager_plan",
    )
    binds = {f"name{index}": name for index, name in enumerate(parameter_names)}
    placeholders = ", ".join(f":name{index}" for index in range(len(parameter_names)))
    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select name, value, display_value, isdefault, issys_modifiable, ispdb_modifiable "
                f"from v$parameter where name in ({placeholders}) order by name",
                binds,
            )
            parameters = [
                {
                    "name": str(name), "value": str(value) if value is not None else None,
                    "display_value": str(display_value) if display_value is not None else None,
                    "isdefault": str(isdefault), "issys_modifiable": str(modifiable),
                    "ispdb_modifiable": str(pdb_modifiable),
                }
                for name, value, display_value, isdefault, modifiable, pdb_modifiable in cursor
            ]
            cursor.execute(
                "select name, value, unit from v$pgastat "
                "where name in ('aggregate PGA target parameter', 'aggregate PGA auto target', "
                "'global memory bound', 'total PGA allocated', 'maximum PGA allocated', "
                "'over allocation count', 'extra bytes read/written') order by name"
            )
            pga_statistics = [
                {"name": str(name), "value": int(value) if value is not None else None,
                 "unit": str(unit) if unit is not None else None}
                for name, value, unit in cursor
            ]
            cursor.execute(
                "select pga_target_for_estimate, estd_pga_cache_hit_percentage, "
                "estd_overalloc_count, estd_extra_bytes_rw "
                "from v$pga_target_advice order by pga_target_for_estimate"
            )
            pga_target_advice = [
                {
                    "pga_target_for_estimate": int(target),
                    "estimated_cache_hit_percentage": float(cache_hit) if cache_hit is not None else None,
                    "estimated_overalloc_count": int(overalloc) if overalloc is not None else None,
                    "estimated_extra_bytes_read_written": int(extra_bytes) if extra_bytes is not None else None,
                }
                for target, cache_hit, overalloc, extra_bytes in cursor
            ]
        return {
            "connection": connection_name,
            "parameters": parameters,
            "pga_statistics": pga_statistics,
            "pga_target_advice": pga_target_advice,
        }
    finally:
        connection.close()

def run_saved_scheduler_job(
    connection_name: str, job_name: str, confirmed: bool
) -> dict[str, object]:
    """Submit one existing saved Oracle Scheduler job asynchronously.

    This is a persistent operation because the job can change database data.
    The owner-qualified job name must be a simple identifier pair, the job
    must exist and be enabled, and no active instance of that job may exist.
    """
    if not confirmed:
        raise ValueError("confirmed must be true after explicit approval for this write operation.")
    match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_$#]{0,29})\.([A-Za-z][A-Za-z0-9_$#]{0,29})", job_name.strip())
    if match is None:
        raise ValueError("job_name must be owner-qualified, for example SYS.FPY_WEEKLY.")
    owner, name = (value.upper() for value in match.groups())
    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select enabled, state from dba_scheduler_jobs where owner = :owner and job_name = :job_name",
                {"owner": owner, "job_name": name},
            )
            job = cursor.fetchone()
            if job is None:
                raise ValueError(f"Scheduler job {owner}.{name} was not found.")
            if str(job[0]).upper() != "TRUE":
                raise ValueError(f"Scheduler job {owner}.{name} is not enabled.")
            cursor.execute(
                "select count(*) from dba_scheduler_running_jobs where owner = :owner and job_name = :job_name",
                {"owner": owner, "job_name": name},
            )
            if int(cursor.fetchone()[0]) > 0:
                raise ValueError(f"Scheduler job {owner}.{name} is already running.")
            cursor.execute(
                "begin dbms_scheduler.run_job(job_name => :job_name, use_current_session => false); end;",
                {"job_name": f"{owner}.{name}"},
            )
        return {
            "connection": connection_name,
            "job_name": f"{owner}.{name}",
            "state_before_submission": str(job[1]),
            "status": "submitted_asynchronously",
        }
    finally:
        connection.close()

def create_saved_oracle_index(
    connection_name: str,
    owner: str,
    table_name: str,
    index_name: str,
    columns: list[str],
    confirmed: bool,
) -> dict[str, object]:
    """Create one normal Oracle index on a saved target.

    This is a persistent DDL operation. It permits only simple Oracle
    identifiers, requires explicit confirmation, and refuses an existing
    identical index definition. It performs no DML, drop, or replacement.
    """
    identifier = re.compile(r"[A-Za-z][A-Za-z0-9_$#]{0,29}")
    if not confirmed:
        raise ValueError("confirmed must be true after explicit approval for this write operation.")
    if not all(identifier.fullmatch(value) for value in (owner, table_name, index_name)):
        raise ValueError("owner, table_name, and index_name must be simple Oracle identifiers.")
    if not 1 <= len(columns) <= 16 or not all(identifier.fullmatch(column) for column in columns):
        raise ValueError("columns must contain one to 16 simple Oracle column identifiers.")

    safe_owner = owner.upper()
    safe_table = table_name.upper()
    safe_index = index_name.upper()
    safe_columns = [column.upper() for column in columns]
    connection = _connect_saved_oracle(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select index_name from dba_indexes "
                "where owner = :owner and index_name = :index_name",
                {"owner": safe_owner, "index_name": safe_index},
            )
            if cursor.fetchone() is not None:
                raise ValueError(f"Index {safe_owner}.{safe_index} already exists.")
            cursor.execute(
                "select index_name from dba_indexes "
                "where table_owner = :owner and table_name = :table_name and index_type = 'NORMAL'",
                {"owner": safe_owner, "table_name": safe_table},
            )
            existing_names = [str(row[0]) for row in cursor]
            for existing_name in existing_names:
                cursor.execute(
                    "select column_name, descend from dba_ind_columns "
                    "where index_owner = :owner and index_name = :index_name "
                    "order by column_position",
                    {"owner": safe_owner, "index_name": existing_name},
                )
                existing_columns = [(str(row[0]), str(row[1])) for row in cursor]
                if existing_columns == [(column, "ASC") for column in safe_columns]:
                    raise ValueError(
                        f"Identical index {safe_owner}.{existing_name} already exists on "
                        f"{safe_owner}.{safe_table}."
                    )
            cursor.execute(
                f"create index {safe_owner}.{safe_index} on {safe_owner}.{safe_table} "
                f"({', '.join(safe_columns)})"
            )
        return {
            "connection": connection_name,
            "owner": safe_owner,
            "table_name": safe_table,
            "index_name": safe_index,
            "columns": safe_columns,
            "status": "created",
        }
    finally:
        connection.close()

if __name__ == "__main__":
    mcp.run(transport="stdio")
