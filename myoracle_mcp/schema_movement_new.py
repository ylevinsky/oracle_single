"""Schema movement and comparison without Oracle Data Pump.

Read-only inventory matches :mod:`schema_movement` but does not query
``DBA_DATAPUMP_JOBS``. Actual schema copies use :mod:`schema_sql_copy`
(DBMS_METADATA and SQL inserts) instead of export/import through Data Pump.
"""

from __future__ import annotations

from typing import Any, Callable

import schema_sql_copy
from schema_datapump import normalize_schemas
from schema_movement import (  # re-export shared read-only helpers
    APPLICATION_TABLE_LIST_SQL,
    CONTAINER_SQL,
    PDB_SQL,
    compare_application_catalogs,
    collect_application_catalog,
    enter_open_pluggable_database,
    list_user_tables,
    physical_row_count,
    _mentions,
    _text,
)
from schema_movement import (  # inventory SQL reused; collection differs below
    JOB_SQL,
    LINK_SQL,
    MVIEW_SQL,
    SCHEMA_SQL,
    SEGMENT_SQL,
    TABLE_SQL,
    TOP_TABLE_SQL,
)

PYTHON_MOVEMENT_MARKERS = (
    "DBMS_METADATA",
    "SCHEMA_SQL_COPY",
    "COPY_SCHEMA",
    "COPY_SAVED_SCHEMA",
    "DBMS_MVIEW",
    "NETWORK_LINK",
    "MV_REFRESH",
)


def collect_inventory(cursor: Any) -> dict[str, Any]:
    """Read schema and movement metadata. Every statement is a SELECT."""
    errors: list[str] = []

    def query(sql: str) -> list[tuple]:
        try:
            cursor.execute(sql)
            return list(cursor)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            return []

    schemas = {
        str(username): {"account_status": str(status)}
        for username, status in query(SCHEMA_SQL)
    }
    for owner, total_bytes in query(SEGMENT_SQL):
        schemas.setdefault(str(owner), {})["segment_bytes"] = int(total_bytes or 0)
    for owner, tables, num_rows, last_analyzed in query(TABLE_SQL):
        entry = schemas.setdefault(str(owner), {})
        entry["table_count"] = int(tables or 0)
        entry["statistics_num_rows"] = int(num_rows or 0)
        entry["last_analyzed"] = _text(last_analyzed)
    top_tables: dict[str, list[dict[str, Any]]] = {}
    for owner, table_name, num_rows, last_analyzed in query(TOP_TABLE_SQL):
        top_tables.setdefault(str(owner), []).append(
            {
                "table_name": str(table_name),
                "statistics_num_rows": int(num_rows) if num_rows is not None else None,
                "last_analyzed": _text(last_analyzed),
            }
        )
    links = [
        {
            "owner": str(owner),
            "db_link": str(db_link),
            "username": _text(username),
            "host": _text(host),
        }
        for owner, db_link, username, host in query(LINK_SQL)
    ]
    materialized_views = [
        {
            "owner": str(owner),
            "mview_name": str(name),
            "master_link": _text(master_link),
            "last_refresh_date": _text(refreshed),
            "staleness": _text(staleness),
            "compile_state": _text(compile_state),
        }
        for owner, name, master_link, refreshed, staleness, compile_state in query(MVIEW_SQL)
    ]
    jobs = [
        {
            "owner": str(owner),
            "job_name": str(job_name),
            "enabled": _text(enabled),
            "state": _text(state),
            "last_start_date": _text(last_start),
            "job_action": _text(job_action),
        }
        for owner, job_name, enabled, state, last_start, job_action in query(JOB_SQL)
    ]
    return {
        "schemas": schemas,
        "top_tables": top_tables,
        "database_links": links,
        "materialized_views": materialized_views,
        "scheduler_jobs": jobs,
        "query_errors": errors,
        "movement_method": "python_dbms_metadata_sql",
    }


def compare_inventories(
    source: dict[str, Any],
    target: dict[str, Any],
    source_aliases: list[str],
    target_aliases: list[str],
) -> dict[str, Any]:
    """Classify schemas and paths that can move data without Data Pump."""
    source_names = set(source["schemas"])
    target_names = set(target["schemas"])
    both = sorted(source_names & target_names)

    def matching_links(inventory: dict[str, Any], aliases: list[str]) -> list[dict[str, Any]]:
        return [link for link in inventory["database_links"] if _mentions(link.get("host"), aliases)]

    def matching_jobs(inventory: dict[str, Any], aliases: list[str]) -> list[dict[str, Any]]:
        matched = []
        for job in inventory["scheduler_jobs"]:
            action = f"{job.get('job_name') or ''} {job.get('job_action') or ''}"
            if _mentions(action, aliases) or _mentions(action, list(PYTHON_MOVEMENT_MARKERS)):
                matched.append(job)
        return matched

    shared = []
    for name in both:
        source_schema = source["schemas"][name]
        target_schema = target["schemas"][name]
        shared.append(
            {
                "schema": name,
                "source_table_count": source_schema.get("table_count", 0),
                "target_table_count": target_schema.get("table_count", 0),
                "source_statistics_num_rows": source_schema.get("statistics_num_rows", 0),
                "target_statistics_num_rows": target_schema.get("statistics_num_rows", 0),
                "source_segment_bytes": source_schema.get("segment_bytes", 0),
                "target_segment_bytes": target_schema.get("segment_bytes", 0),
            }
        )
    remote_mviews = [
        view
        for inventory in (source, target)
        for view in inventory["materialized_views"]
        if view.get("master_link")
    ]
    return {
        "schemas_only_on_source": sorted(source_names - target_names),
        "schemas_only_on_target": sorted(target_names - source_names),
        "schemas_on_both": shared,
        "source_links_to_target": matching_links(source, target_aliases),
        "target_links_to_source": matching_links(target, source_aliases),
        "source_movement_jobs": matching_jobs(source, target_aliases),
        "target_movement_jobs": matching_jobs(target, source_aliases),
        "materialized_views_using_a_database_link": remote_mviews,
        "copy_method": "python_dbms_metadata_sql",
    }


def copy_schemas(
    source_name: str,
    target_name: str,
    schemas: list[str],
    *,
    confirmed: bool,
    tablespace_remap: dict[str, str] | None,
    connect: Callable[[str], Any],
    resume: bool = False,
) -> dict[str, Any]:
    """Copy schemas with DBMS_METADATA and row inserts. Stop when the target has one."""
    if source_name == target_name:
        raise ValueError("source and target connections must be different")
    names = normalize_schemas(schemas)
    remap = schema_sql_copy.normalize_remap(tablespace_remap)
    previews: list[dict[str, Any]] = []
    for schema in names:
        preview = schema_sql_copy.copy_schema(
            source_name,
            target_name,
            schema,
            confirmed=False,
            tablespace_remap=remap,
            connect=connect,
            resume=resume,
        )
        previews.append(preview)
    existing = [
        preview["schema"]
        for preview in previews
        if preview.get("status") == "stopped"
    ]
    if existing:
        return {
            "status": "stopped",
            "reason": "destination schema already exists",
            "source": source_name,
            "target": target_name,
            "schemas": names,
            "existing_on_target": existing,
            "copy_method": "python_dbms_metadata_sql",
            "tablespace_remap": remap,
        }
    plan = {
        "source": source_name,
        "target": target_name,
        "schemas": names,
        "tablespace_remap": remap,
        "copy_method": "python_dbms_metadata_sql",
    }
    if not confirmed:
        return {"status": "not_confirmed", **plan}

    per_schema: list[dict[str, Any]] = []
    for schema in names:
        result = schema_sql_copy.copy_schema(
            source_name,
            target_name,
            schema,
            confirmed=True,
            tablespace_remap=remap,
            connect=connect,
            resume=resume,
        )
        per_schema.append(result)
        if result.get("status") == "stopped":
            done = [item["schema"] for item in per_schema if item.get("status") != "stopped"]
            pending = [name for name in names if name not in {*done, schema}]
            return {
                "status": "stopped",
                "reason": result.get("reason", "copy stopped"),
                "completed_schemas": done,
                "pending_schemas": pending,
                "per_schema": per_schema,
                **plan,
            }
    errors = sum(len(item.get("errors") or []) for item in per_schema)
    statuses = {str(item.get("status")) for item in per_schema}
    if errors:
        overall = "copied_with_errors"
    elif statuses == {"copied"}:
        overall = "copied"
    else:
        overall = "copied_with_errors"
    return {
        "status": overall,
        **plan,
        "per_schema": per_schema,
        "objects_created": sum(int(item.get("objects_created") or 0) for item in per_schema),
        "grants_applied": sum(int(item.get("grants_applied") or 0) for item in per_schema),
    }
