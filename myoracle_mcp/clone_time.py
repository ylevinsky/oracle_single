"""Clone snapshot time and instance start time for a saved Oracle connection.

Answers "when was the source database snapshotted for this VM-snapshot
clone?" by weighing the frozen datafile-header checkpoints against this
instance's own startup time:

- Fresh clone: the headers are still frozen at a pre-startup checkpoint, so
  the snapshot time is that checkpoint time.
- Aged clone: this instance has been open long enough to overwrite the
  headers with its own checkpoints. The checkpoint time is then meaningless
  for dating the snapshot, so the snapshot window is derived from this
  clone's own ``v$archived_log`` instead: the clone's control file carries
  the source's archive history up to the snapshot moment plus the archives
  this instance created after opening. The last log fully archived before
  this instance started bounds the snapshot from below; this instance's
  startup bounds it from above.

Nothing is persisted.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Callable

from ephemeral_oracle import effective_connection

STARTUP_SQL = """
    select instance_name,
           host_name,
           to_char(startup_time, 'YYYY-MM-DD HH24:MI:SS'),
           to_char(sysdate, 'YYYY-MM-DD HH24:MI:SS')
      from v$instance
"""

CLONE_SQL = """
    select min(checkpoint_change#),
           max(checkpoint_change#),
           to_char(min(checkpoint_time), 'YYYY-MM-DD HH24:MI:SS'),
           to_char(max(checkpoint_time), 'YYYY-MM-DD HH24:MI:SS'),
           count(*)
      from v$datafile_header
"""

LAST_ARCHIVED_BEFORE_STARTUP_SQL = """
    select sequence#, first_change#, next_change#,
           to_char(first_time, 'YYYY-MM-DD HH24:MI:SS'),
           to_char(next_time, 'YYYY-MM-DD HH24:MI:SS')
      from v$archived_log
     where next_time <= TO_DATE('{startup}', 'YYYY-MM-DD HH24:MI:SS')
     order by next_time desc
     fetch first 1 rows only
"""

SPANNING_LOG_SQL = """
    select sequence#, first_change#, next_change#,
           to_char(first_time, 'YYYY-MM-DD HH24:MI:SS'),
           to_char(next_time, 'YYYY-MM-DD HH24:MI:SS')
      from v$archived_log
     where first_time <= TO_DATE('{startup}', 'YYYY-MM-DD HH24:MI:SS')
       and (next_time > TO_DATE('{startup}', 'YYYY-MM-DD HH24:MI:SS')
            or next_time is null)
     order by sequence#
     fetch first 3 rows only
"""

FIRST_LOGS_AFTER_STARTUP_SQL = """
    select sequence#, first_change#, next_change#,
           to_char(first_time, 'YYYY-MM-DD HH24:MI:SS'),
           to_char(next_time, 'YYYY-MM-DD HH24:MI:SS')
      from v$archived_log
     where first_time >= TO_DATE('{startup}', 'YYYY-MM-DD HH24:MI:SS')
     order by sequence#
     fetch first 5 rows only
"""

_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def _archived_log_entry(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    sequence, first_change, next_change, first_time, next_time = row
    return {
        "sequence#": int(sequence),
        "first_change#": int(first_change),
        "next_change#": int(next_change) if next_change is not None else None,
        "first_time": str(first_time),
        "next_time": str(next_time) if next_time is not None else None,
    }


def _snapshot_from_archived_logs(
    startup_time: str,
    cursor: Any,
) -> dict[str, Any]:
    """Derive the snapshot window from this clone's own archive history.

    Returns snapshot fields for the aged-clone case. Any query failure is
    captured in ``archive_error`` instead of failing the whole check, since
    the startup/checkpoint data is still useful on its own.
    """
    result: dict[str, Any] = {
        "snapshot_time": None,
        "snapshot_method": "unknown",
        "snapshot_window_start": None,
        "snapshot_window_end": None,
        "last_source_scn_archived": None,
        "last_log_before_startup": None,
        "spanning_logs": [],
        "first_logs_after_startup": [],
        "archive_error": None,
    }
    try:
        cursor.execute(LAST_ARCHIVED_BEFORE_STARTUP_SQL.format(startup=startup_time))
        last_before = _archived_log_entry(cursor.fetchone())
        cursor.execute(SPANNING_LOG_SQL.format(startup=startup_time))
        spanning = [
            entry
            for entry in (_archived_log_entry(row) for row in cursor.fetchmany(4))
            if entry is not None
        ]
        cursor.execute(FIRST_LOGS_AFTER_STARTUP_SQL.format(startup=startup_time))
        first_after = [
            entry
            for entry in (_archived_log_entry(row) for row in cursor.fetchmany(6))
            if entry is not None
        ]
    except Exception as exc:
        result["archive_error"] = f"{type(exc).__name__}: {exc}"
        return result

    result["last_log_before_startup"] = last_before
    result["spanning_logs"] = spanning
    result["first_logs_after_startup"] = first_after
    if last_before is not None:
        result["last_source_scn_archived"] = last_before["next_change#"]

    window_start: str | None = None
    if spanning:
        window_start = spanning[0]["first_time"]
    elif last_before is not None:
        window_start = last_before["next_time"]
    if window_start is not None:
        result["snapshot_method"] = "archived_log_window"
        result["snapshot_window_start"] = window_start
        result["snapshot_window_end"] = startup_time
    return result


def _interpret(
    latest_checkpoint_time: str, startup_time: str, snapshot_consistent: bool
) -> tuple[bool, str]:
    """Decide whether the datafile headers still carry the original snapshot state.

    Returns ``(headers_advanced, note)``. On a freshly started VM-snapshot
    clone the headers are frozen at the snapshot moment, before this
    instance started, and ``clone_time`` is the snapshot time. Once this
    instance has checkpointed, the headers carry its own timestamps, so
    ``clone_time`` is only the latest checkpoint and the original snapshot
    time must come from this clone's archived-log history instead.
    """
    try:
        checkpoint = datetime.strptime(latest_checkpoint_time, _TIME_FORMAT)
        startup = datetime.strptime(startup_time, _TIME_FORMAT)
    except ValueError:
        return False, "could not parse checkpoint/startup timestamps."
    headers_advanced = checkpoint >= startup
    if headers_advanced:
        return (
            True,
            "datafile headers were written after this instance started, so "
            "clone_time is this instance's own last checkpoint, not the "
            "original snapshot time. See snapshot_window_start/"
            "snapshot_window_end and last_source_scn_archived, derived from "
            "this clone's own v$archived_log, for when the source was "
            "snapshotted.",
        )
    if not snapshot_consistent:
        return (
            False,
            "headers predate startup but checkpoint times differ between "
            "files; inspect v$datafile_header per file before trusting "
            "clone_time.",
        )
    return (
        False,
        "headers are frozen at a pre-startup checkpoint shared by all "
        "files; clone_time is the last checkpoint of the source database "
        "before the VM snapshot was taken.",
    )


def clone_and_start_time(
    base_connection_name: str,
    base_connection: dict[str, Any],
    host: str | None,
    port: Any,
    connect: Callable[[dict[str, Any]], Any],
) -> dict[str, Any]:
    """Return the clone snapshot time and the instance start time.

    The snapshot time is the maximum ``checkpoint_time`` frozen in the
    datafile headers when those headers still predate this instance's
    startup. When the headers were already overwritten by this instance's
    own checkpoints, the snapshot window is derived from this clone's own
    ``v$archived_log`` instead. The start time is ``v$instance.startup_time``.
    The saved host is used unless ``host`` (and optionally ``port``) is
    overridden; overrides are never persisted.
    """
    effective = effective_connection(
        base_connection_name, base_connection, host, port, require_host=False
    )

    started = time.monotonic()
    connection = connect(effective)
    try:
        with connection.cursor() as cursor:
            cursor.execute(STARTUP_SQL)
            instance_name, hostname, startup_time, sysdate_now = cursor.fetchone()
            cursor.execute(CLONE_SQL)
            min_ckpt_scn, max_ckpt_scn, min_ckpt_time, max_ckpt_time, file_count = (
                cursor.fetchone()
            )
            snapshot_consistent = str(min_ckpt_time) == str(max_ckpt_time)
            headers_advanced, note = _interpret(
                str(max_ckpt_time), str(startup_time), bool(snapshot_consistent)
            )
            snapshot: dict[str, Any] = {
                "snapshot_time": None,
                "snapshot_method": "unknown",
                "snapshot_window_start": None,
                "snapshot_window_end": None,
                "last_source_scn_archived": None,
                "last_log_before_startup": None,
                "spanning_logs": [],
                "first_logs_after_startup": [],
                "archive_error": None,
            }
            if not headers_advanced and bool(snapshot_consistent):
                snapshot["snapshot_time"] = str(max_ckpt_time)
                snapshot["snapshot_method"] = "datafile_header_frozen"
                snapshot["snapshot_window_start"] = str(min_ckpt_time)
                snapshot["snapshot_window_end"] = str(max_ckpt_time)
            else:
                try:
                    datetime.strptime(str(startup_time), _TIME_FORMAT)
                except ValueError:
                    snapshot["archive_error"] = (
                        "could not parse startup_time; skipped archived-log lookup."
                    )
                else:
                    snapshot = _snapshot_from_archived_logs(str(startup_time), cursor)
                    if snapshot["snapshot_method"] == "unknown" and headers_advanced:
                        note = (
                            "datafile headers were written after this instance "
                            "started, so clone_time is this instance's own last "
                            "checkpoint, not the original snapshot time, and no "
                            "usable archive history was found. For the snapshot "
                            "moment read the first startup/crash-recovery entries "
                            "in the clone's alert log instead."
                        )
    finally:
        close = getattr(connection, "close", None)
        if callable(close):
            close()
    elapsed_ms = int((time.monotonic() - started) * 1000)
    sid = str(effective.get("sid") or effective.get("database"))

    return {
        "base_connection_name": str(base_connection_name),
        "host": str(effective["host"]),
        "port": int(effective["port"]),
        "sid": sid,
        "instance_name": str(instance_name),
        "host_name": str(hostname),
        "startup_time": str(startup_time),
        "database_time": str(sysdate_now),
        "clone_time": str(max_ckpt_time),
        "clone_time_is_snapshot_consistent": bool(snapshot_consistent),
        "clone_time_looks_advanced": headers_advanced,
        "interpretation": note,
        "checkpoint_time_earliest": str(min_ckpt_time),
        "checkpoint_time_latest": str(max_ckpt_time),
        "checkpoint_scn_min": int(min_ckpt_scn),
        "checkpoint_scn_max": int(max_ckpt_scn),
        "datafile_count": int(file_count),
        **snapshot,
        "elapsed_ms": elapsed_ms,
    }
