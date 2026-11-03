"""Exact optimizer statistics for non-Oracle-maintained tables.

Each table is gathered with ``DBMS_STATS.GATHER_TABLE_STATS`` at
``ESTIMATE_PERCENT => 100`` so ``DBA_TABLES.NUM_ROWS`` is a full count.
Connections run concurrently. Inside one connection, tables run one after
another, and each gather uses the requested parallel degree. The saved
connection itself is opened by the caller.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

TABLE_SQL = """
    select t.owner, t.table_name
      from dba_tables t
      join dba_users u on u.username = t.owner
     where u.oracle_maintained = 'N'
       and t.temporary = 'N'
       and t.nested = 'NO'
       and nvl(t.external, 'NO') = 'NO'
       and nvl(t.secondary, 'N') = 'N'
       and instr(t.table_name, '$') = 0
       and t.table_name not like 'BIN$%'
     order by t.owner, t.table_name
"""

LOCKED_TABLE_SQL = """
    select t.owner, t.table_name
      from dba_tables t
      join dba_users u on u.username = t.owner
      join dba_tab_statistics s
        on s.owner = t.owner
       and s.table_name = t.table_name
       and s.object_type = 'TABLE'
     where u.oracle_maintained = 'N'
       and t.temporary = 'N'
       and t.nested = 'NO'
       and nvl(t.external, 'NO') = 'NO'
       and nvl(t.secondary, 'N') = 'N'
       and instr(t.table_name, '$') = 0
       and t.table_name not like 'BIN$%'
       and (
            s.stattype_locked is not null
            or (
                s.stattype_locked is null
                and nvl(s.last_analyzed, date '1900-01-01') < sysdate - 1
                and exists (
                    select 1
                      from dba_tab_statistics earlier
                     where earlier.owner = t.owner
                       and earlier.object_type = 'TABLE'
                       and earlier.table_name < t.table_name
                       and earlier.last_analyzed > sysdate - 6/24
                )
                and exists (
                    select 1
                      from dba_tab_statistics later
                     where later.owner = t.owner
                       and later.object_type = 'TABLE'
                       and later.table_name > t.table_name
                       and later.stattype_locked is not null
                )
            )
       )
     order by t.owner, t.table_name
"""

UNLOCK_SQL = """
begin
  dbms_stats.unlock_table_stats(ownname => :owner, tabname => :table_name);
end;
"""

GATHER_SQL = """
begin
  dbms_stats.gather_table_stats(
    ownname => :owner,
    tabname => :table_name,
    estimate_percent => :estimate_percent,
    degree => :degree,
    cascade => true,
    method_opt => 'FOR ALL COLUMNS SIZE 1',
    granularity => 'ALL'
  );
end;
"""

READ_SQL = """
    select num_rows, to_char(last_analyzed, 'YYYY-MM-DD HH24:MI:SS')
      from dba_tables
     where owner = :owner and table_name = :table_name
"""

MAX_CONNECTIONS = 4
MAX_TIMEOUT_SECONDS = 3 * 60 * 60


def validate_request(
    connection_names: list[str], degree: int, timeout_seconds: int
) -> list[str]:
    """Return cleaned connection names or raise ValueError."""
    if not isinstance(connection_names, list) or not 1 <= len(connection_names) <= MAX_CONNECTIONS:
        raise ValueError("connection_names must contain 1 to 4 saved connection names.")
    names: list[str] = []
    for name in connection_names:
        text = str(name).strip()
        if not text:
            raise ValueError("connection names must not be empty.")
        names.append(text)
    if len(set(names)) != len(names):
        raise ValueError("connection_names must not contain duplicates.")
    if isinstance(degree, bool) or not isinstance(degree, int) or not 1 <= degree <= 128:
        raise ValueError("degree must be an integer from 1 to 128.")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS
    ):
        raise ValueError("timeout_seconds must be an integer from 1 to 10800 (3 hours).")
    return names


def validate_estimate(estimate_percent: int) -> int:
    """Return a sample percent from 1 to 100."""
    if (
        isinstance(estimate_percent, bool)
        or not isinstance(estimate_percent, int)
        or not 1 <= estimate_percent <= 100
    ):
        raise ValueError("estimate_percent must be an integer from 1 to 100.")
    return estimate_percent


def _timeout_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "timeout" in message or "dpy-4024" in message or "ora-01013" in message


def _entry(
    owner: str,
    table_name: str,
    status: str,
    *,
    exact_row_count: int | None = None,
    last_analyzed: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "owner": owner,
        "table_name": table_name,
        "status": status,
        "exact_row_count": exact_row_count,
    }
    if last_analyzed is not None:
        row["last_analyzed"] = last_analyzed
    if error is not None:
        row["error"] = error
    return row


def gather_on_cursor(
    cursor: Any,
    *,
    degree: int,
    timeout_seconds: int,
    now: Callable[[], float] = time.monotonic,
    on_table: Callable[[dict[str, Any]], None] | None = None,
    skip: set[tuple[str, str]] | None = None,
    estimate_percent: int = 100,
    unlock_statistics: bool = False,
    locked_only: bool = False,
) -> dict[str, Any]:
    """Gather statistics for every eligible table on an open cursor."""
    estimate_percent = validate_estimate(estimate_percent)
    started = now()
    deadline = started + timeout_seconds
    cursor.execute(LOCKED_TABLE_SQL if locked_only else TABLE_SQL)
    tables = [(str(owner), str(table_name)) for owner, table_name in cursor]
    results: list[dict[str, Any]] = []
    stop = False
    skipped = 0
    for owner, table_name in tables:
        if skip and (owner, table_name) in skip:
            skipped += 1
            continue
        if stop or now() >= deadline:
            entry = _entry(owner, table_name, "not_started", error="timeout")
            results.append(entry)
            if on_table is not None:
                on_table(entry)
            stop = True
            continue
        remaining_ms = max(1, int((deadline - now()) * 1000))
        cursor.call_timeout = remaining_ms
        try:
            if unlock_statistics:
                cursor.execute(UNLOCK_SQL, {"owner": owner, "table_name": table_name})
            cursor.execute(
                GATHER_SQL,
                {
                    "owner": owner,
                    "table_name": table_name,
                    "degree": degree,
                    "estimate_percent": estimate_percent,
                },
            )
            cursor.execute(READ_SQL, {"owner": owner, "table_name": table_name})
            row = cursor.fetchone()
            num_rows, last_analyzed = row if row else (None, None)
            entry = _entry(
                owner,
                table_name,
                "gathered",
                exact_row_count=int(num_rows) if num_rows is not None else None,
                last_analyzed=str(last_analyzed) if last_analyzed else None,
            )
        except Exception as exc:
            timed_out = _timeout_error(exc)
            entry = _entry(
                owner,
                table_name,
                "timed_out" if timed_out else "failed",
                error=str(exc).splitlines()[0][:500],
            )
            stop = timed_out
        results.append(entry)
        if on_table is not None:
            on_table(entry)
    gathered = [item for item in results if item["status"] == "gathered"]
    return {
        "estimate_percent": estimate_percent,
        "unlock_statistics": unlock_statistics,
        "locked_only": locked_only,
        "degree": degree,
        "timeout_seconds": timeout_seconds,
        "elapsed_seconds": round(now() - started, 1),
        "tables_selected": len(tables),
        "tables_skipped": skipped,
        "tables_gathered": len(gathered),
        "tables_failed": sum(1 for item in results if item["status"] == "failed"),
        "tables_timed_out": sum(1 for item in results if item["status"] == "timed_out"),
        "tables_not_started": sum(1 for item in results if item["status"] == "not_started"),
        "exact_row_count_total": sum(
            int(item["exact_row_count"])
            for item in gathered
            if item["exact_row_count"] is not None
        ),
        "tables": results,
    }


def _progress_path(
    progress_dir: Path | None, connection_name: str, estimate_percent: int = 100
) -> Path | None:
    if progress_dir is None:
        return None
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in connection_name)
    suffix = "" if estimate_percent == 100 else f"_e{estimate_percent}"
    return progress_dir / f"{safe}{suffix}.jsonl"


def _recorded_tables(path: Path | None) -> set[tuple[str, str]]:
    recorded: set[tuple[str, str]] = set()
    if path is None or not path.exists():
        return recorded
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        owner = row.get("owner")
        table_name = row.get("table_name")
        if owner and table_name:
            recorded.add((str(owner), str(table_name)))
    return recorded


_background_lock = threading.Lock()
_background: dict[str, Any] = {"thread": None, "result": None, "error": None}


def gather_parallel(
    connection_names: list[str],
    connect: Callable[[str], tuple[Any, Any]],
    degree: int,
    timeout_seconds: int,
    *,
    progress_dir: Path | None = None,
    now: Callable[[], float] = time.monotonic,
    resume: bool = False,
    estimate_percent: int = 100,
    unlock_statistics: bool = False,
    locked_only: bool = False,
) -> dict[str, Any]:
    """Gather statistics on each connection at the same time."""
    names = validate_request(connection_names, degree, timeout_seconds)
    estimate_percent = validate_estimate(estimate_percent)
    lock = threading.Lock()
    if progress_dir is not None:
        progress_dir.mkdir(parents=True, exist_ok=True)

    def run_one(name: str) -> dict[str, Any]:
        path = _progress_path(progress_dir, name, estimate_percent)
        skip = _recorded_tables(path) if resume else set()
        if path is not None and path.exists() and not resume:
            path.unlink()

        def on_table(entry: dict[str, Any]) -> None:
            if path is None:
                return
            line = json.dumps({"connection": name, **entry}) + "\n"
            with lock:
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(line)

        database = None
        try:
            database, cursor = connect(name)
            try:
                outcome = gather_on_cursor(
                    cursor,
                    degree=degree,
                    timeout_seconds=timeout_seconds,
                    now=now,
                    on_table=on_table,
                    skip=skip,
                    estimate_percent=estimate_percent,
                    unlock_statistics=unlock_statistics,
                    locked_only=locked_only,
                )
            finally:
                close_cursor = getattr(cursor, "close", None)
                if callable(close_cursor):
                    close_cursor()
            outcome["connection"] = name
            outcome["status"] = "completed"
            if path is not None:
                outcome["progress_file"] = str(path)
            return outcome
        except Exception as exc:
            message = str(exc).splitlines()[0][:500]
            if path is not None:
                line = json.dumps({"connection": name, "status": "failed", "error": message}) + "\n"
                with lock:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("a", encoding="utf-8") as handle:
                        handle.write(line)
            return {
                "connection": name,
                "status": "failed",
                "error": message,
                "tables": [],
                **({"progress_file": str(path)} if path is not None else {}),
            }
        finally:
            if database is not None:
                close = getattr(database, "close", None)
                if callable(close):
                    close()

    started = now()
    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        outcomes = list(pool.map(run_one, names))
    result = {
        "degree": degree,
        "estimate_percent": estimate_percent,
        "unlock_statistics": unlock_statistics,
        "locked_only": locked_only,
        "timeout_seconds": timeout_seconds,
        "parallel_connections": len(names),
        "elapsed_seconds": round(now() - started, 1),
        "resume": resume,
        "connections": outcomes,
    }
    if progress_dir is not None:
        summary = {
            "degree": degree,
            "estimate_percent": estimate_percent,
            "unlock_statistics": unlock_statistics,
            "locked_only": locked_only,
            "timeout_seconds": timeout_seconds,
            "elapsed_seconds": result["elapsed_seconds"],
            "resume": resume,
            "connections": [
                {
                    "connection": item.get("connection"),
                    "status": item.get("status"),
                    "error": item.get("error"),
                    "tables_selected": item.get("tables_selected"),
                    "tables_skipped": item.get("tables_skipped"),
                    "tables_gathered": item.get("tables_gathered"),
                    "tables_failed": item.get("tables_failed"),
                    "tables_timed_out": item.get("tables_timed_out"),
                    "tables_not_started": item.get("tables_not_started"),
                    "exact_row_count_total": item.get("exact_row_count_total"),
                    "progress_file": item.get("progress_file"),
                }
                for item in outcomes
            ],
        }
        summary_name = "summary.json" if estimate_percent == 100 else f"summary_e{estimate_percent}.json"
        summary_path = progress_dir / summary_name
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        result["summary_file"] = str(summary_path)
    return result


def start_background(
    connection_names: list[str],
    connect: Callable[[str], tuple[Any, Any]],
    degree: int,
    timeout_seconds: int,
    progress_dir: Path,
    resume: bool,
    estimate_percent: int = 100,
    unlock_statistics: bool = False,
    locked_only: bool = False,
) -> dict[str, Any]:
    """Start statistics gathering in this process and return without waiting."""
    names = validate_request(connection_names, degree, timeout_seconds)
    estimate_percent = validate_estimate(estimate_percent)
    with _background_lock:
        thread = _background.get("thread")
        if isinstance(thread, threading.Thread) and thread.is_alive():
            return {
                "status": "already_running",
                "progress_dir": str(progress_dir),
                "connections": names,
            }

        def target() -> None:
            try:
                _background["result"] = gather_parallel(
                    names,
                    connect,
                    degree,
                    timeout_seconds,
                    progress_dir=progress_dir,
                    resume=resume,
                    estimate_percent=estimate_percent,
                    unlock_statistics=unlock_statistics,
                    locked_only=locked_only,
                )
                _background["error"] = None
            except Exception as exc:
                _background["error"] = str(exc).splitlines()[0][:500]
                _background["result"] = None

        worker = threading.Thread(target=target, name="exact-table-stats", daemon=False)
        _background["thread"] = worker
        _background["result"] = None
        _background["error"] = None
        worker.start()
    return {
        "status": "started",
        "degree": degree,
        "estimate_percent": estimate_percent,
        "unlock_statistics": unlock_statistics,
        "locked_only": locked_only,
        "timeout_seconds": timeout_seconds,
        "resume": resume,
        "connections": names,
        "progress_dir": str(progress_dir),
    }
