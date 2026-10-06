"""Read-only comparison of schemas and data-movement paths between two databases."""

from __future__ import annotations

import re
import sys
from typing import Any

SCHEMA_SQL = """
    select username, account_status
      from dba_users
     where oracle_maintained = 'N'
     order by username
"""

SEGMENT_SQL = """
    select owner, sum(bytes)
      from dba_segments
     where owner in (select username from dba_users where oracle_maintained = 'N')
     group by owner
"""

TABLE_SQL = """
    select owner,
           count(*),
           sum(nvl(num_rows, 0)),
           to_char(max(last_analyzed), 'YYYY-MM-DD HH24:MI:SS')
      from dba_tables
     where owner in (select username from dba_users where oracle_maintained = 'N')
     group by owner
"""

TOP_TABLE_SQL = """
    select owner, table_name, num_rows,
           to_char(last_analyzed, 'YYYY-MM-DD HH24:MI:SS')
      from (
            select owner, table_name, num_rows, last_analyzed,
                   row_number() over (
                       partition by owner order by nvl(num_rows, -1) desc, table_name
                   ) as rank_in_schema
              from dba_tables
             where owner in (select username from dba_users where oracle_maintained = 'N')
           )
     where rank_in_schema <= 8
     order by owner, rank_in_schema
"""

LINK_SQL = """
    select owner, db_link, username, substr(host, 1, 300)
      from dba_db_links
     order by owner, db_link
"""

MVIEW_SQL = """
    select owner, mview_name, master_link,
           to_char(last_refresh_date, 'YYYY-MM-DD HH24:MI:SS'),
           staleness, compile_state
      from dba_mviews
     where owner in (select username from dba_users where oracle_maintained = 'N')
     order by owner, mview_name
"""

JOB_SQL = """
    select j.owner, j.job_name, j.enabled, j.state,
           to_char(j.last_start_date, 'YYYY-MM-DD HH24:MI:SS'),
           substr(j.job_action, 1, 400)
      from dba_scheduler_jobs j
      join dba_users u on u.username = j.owner
     where u.oracle_maintained = 'N'
     order by j.owner, j.job_name
"""

USER_TABLE_SQL = """
    select u.username,
           t.table_name,
           to_char(o.created, 'YYYY-MM-DD HH24:MI:SS')
      from dba_users u
      left join dba_tables t
        on t.owner = u.username
      left join dba_objects o
        on o.owner = t.owner
       and o.object_name = t.table_name
       and o.object_type = 'TABLE'
     where u.oracle_maintained = 'N'
     order by u.username, t.table_name nulls first
"""

DATAPUMP_SQL = """
    select owner_name, job_name, operation, job_mode, state
      from dba_datapump_jobs
     order by owner_name, job_name
"""


CONTAINER_SQL = "select sys_context('userenv','con_name') from dual"
PDB_SQL = """
    select name, open_mode
      from v$pdbs
     where name <> 'PDB$SEED'
     order by name
"""
APPLICATION_TABLE_LIST_SQL = """
    select owner, table_name
      from dba_tables
     where owner in (select username from dba_users where oracle_maintained = 'N')
       and temporary = 'N'
       and nested = 'NO'
       and external = 'NO'
       and table_name not like 'BIN$%'
     order by owner, table_name
"""


def enter_open_pluggable_database(cursor: Any) -> str:
    """Return the current container, moving from the root into the open PDB."""
    cursor.execute(CONTAINER_SQL)
    container = str(cursor.fetchone()[0])
    if container != "CDB$ROOT":
        return container
    cursor.execute(PDB_SQL)
    open_pdbs = [str(name) for name, mode in cursor if str(mode).upper().startswith("READ")]
    if len(open_pdbs) != 1:
        return container
    pdb_name = open_pdbs[0]
    if not re.fullmatch(r"[A-Z][A-Z0-9_$#]{0,127}", pdb_name):
        raise ValueError(f"Unexpected pluggable database name: {pdb_name}")
    cursor.execute(f'alter session set container = "{pdb_name}"')
    return pdb_name


def _text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def list_user_tables(cursor: Any) -> dict[str, Any]:
    """Return non-Oracle-maintained schemas and the tables owned by each."""
    cursor.execute(USER_TABLE_SQL)
    schemas: dict[str, dict[str, Any]] = {}
    for username, table_name, created in cursor:
        schema = schemas.setdefault(str(username), {"tables": []})
        if table_name is not None:
            schema["tables"].append(
                {"table_name": str(table_name), "created": _text(created)}
            )
    return {
        "filter": "DBA_USERS.ORACLE_MAINTAINED = 'N'",
        "schema_count": len(schemas),
        "table_count": sum(len(schema["tables"]) for schema in schemas.values()),
        "schemas": [
            {"schema": name, "table_count": len(schema["tables"]), "tables": schema["tables"]}
            for name, schema in schemas.items()
        ],
    }


APPLICATION_TABLE_SQL = """
    select owner, table_name, num_rows,
           to_char(last_analyzed, 'YYYY-MM-DD HH24:MI:SS')
      from dba_tables
     where owner in (select username from dba_users where oracle_maintained = 'N')
"""

TABLE_STRUCTURE_SQL = """
    select owner, table_name,
           count(*) column_count,
           sum(ora_hash(
               column_name || '|' || data_type || '|' ||
               nvl(to_char(data_length), '-') || '|' ||
               nvl(to_char(data_precision), '-') || '|' ||
               nvl(to_char(data_scale), '-') || '|' ||
               nullable || '|' || to_char(column_id)
           )) structure_hash
      from dba_tab_columns
     where owner in (select username from dba_users where oracle_maintained = 'N')
     group by owner, table_name
"""

APPLICATION_CODE_SQL = """
    select owner, name, type, count(*) line_count,
           sum(ora_hash(rtrim(text, chr(10) || chr(13)))) source_hash
      from dba_source
     where type in ('PROCEDURE', 'FUNCTION', 'PACKAGE', 'PACKAGE BODY')
       and owner in (select username from dba_users where oracle_maintained = 'N')
     group by owner, name, type
"""


def physical_row_count(cursor: Any, owner: str, table_name: str) -> int:
    """Count rows by reading the table. Names must be ordinary Oracle identifiers."""
    if not re.fullmatch(r"[A-Z][A-Z0-9_$#]{0,127}", owner):
        raise ValueError(f"Unexpected schema name: {owner}")
    if not re.fullmatch(r"[A-Z][A-Z0-9_$#]{0,127}", table_name):
        raise ValueError(f"Unexpected table name: {table_name}")
    cursor.execute(f'select count(*) from "{owner}"."{table_name}"')
    return int(cursor.fetchone()[0])


def collect_application_catalog(cursor: Any, *, physical_counts: bool = False) -> dict[str, Any]:
    """Read user tables, column signatures, and application PL/SQL checksums."""
    errors: list[str] = []

    def query(sql: str) -> list[tuple]:
        try:
            cursor.execute(sql)
            return list(cursor)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            return []

    tables: dict[str, dict[str, Any]] = {}
    for owner, table_name, num_rows, last_analyzed in query(APPLICATION_TABLE_SQL):
        tables[f"{owner}.{table_name}"] = {
            "owner": str(owner),
            "table_name": str(table_name),
            "num_rows": int(num_rows) if num_rows is not None else None,
            "last_analyzed": _text(last_analyzed),
        }
    for owner, table_name, column_count, structure_hash in query(TABLE_STRUCTURE_SQL):
        entry = tables.setdefault(
            f"{owner}.{table_name}",
            {"owner": str(owner), "table_name": str(table_name), "num_rows": None, "last_analyzed": None},
        )
        entry["column_count"] = int(column_count or 0)
        entry["structure_hash"] = int(structure_hash or 0)
    if physical_counts:
        counted = 0
        for entry in tables.values():
            entry["num_rows"] = None
            if str(entry["table_name"]).startswith("BIN$"):
                entry["count_source"] = "skipped_recycle_bin"
                continue
            try:
                entry["num_rows"] = physical_row_count(cursor, entry["owner"], entry["table_name"])
                entry["count_source"] = "COUNT(*)"
            except Exception as exc:
                entry["count_error"] = f"{type(exc).__name__}: {exc}"
                errors.append(f"{entry['owner']}.{entry['table_name']}: {entry['count_error']}")
            counted += 1
            if counted % 25 == 0:
                print(
                    f"COUNT(*) {counted} {entry['owner']}.{entry['table_name']}",
                    file=sys.stderr,
                    flush=True,
                )
    code = {
        f"{owner}.{name}.{code_type}": {
            "owner": str(owner),
            "name": str(name),
            "type": str(code_type),
            "line_count": int(line_count or 0),
            "source_hash": int(source_hash or 0),
        }
        for owner, name, code_type, line_count, source_hash in query(APPLICATION_CODE_SQL)
    }
    return {"tables": tables, "code": code, "query_errors": errors}


def _table_status(source: dict[str, Any] | None, target: dict[str, Any] | None) -> str:
    if source is None:
        return "missing_on_ofakim"
    if target is None:
        return "missing_on_dwh"
    same_shape = (
        source.get("column_count") == target.get("column_count")
        and source.get("structure_hash") == target.get("structure_hash")
    )
    return "same_structure" if same_shape else "different_structure"


def _code_status(source: dict[str, Any] | None, target: dict[str, Any] | None) -> str:
    if source is None:
        return "missing_on_ofakim"
    if target is None:
        return "missing_on_dwh"
    same_source = (
        source.get("line_count") == target.get("line_count")
        and source.get("source_hash") == target.get("source_hash")
    )
    return "same" if same_source else "different"


def compare_application_catalogs(
    source: dict[str, Any], target: dict[str, Any]
) -> dict[str, Any]:
    """Compare table presence, column signature, row statistics, and PL/SQL source."""
    table_keys = sorted(set(source["tables"]) | set(target["tables"]))
    tables = []
    for key in table_keys:
        left = source["tables"].get(key)
        right = target["tables"].get(key)
        basis = left or right
        tables.append(
            {
                "schema": basis["owner"],
                "table_name": basis["table_name"],
                "status": _table_status(left, right),
                "ofakim_rows": None if left is None else left.get("num_rows"),
                "dwh_rows": None if right is None else right.get("num_rows"),
                "ofakim_columns": None if left is None else left.get("column_count"),
                "dwh_columns": None if right is None else right.get("column_count"),
                "ofakim_last_analyzed": None if left is None else left.get("last_analyzed"),
                "dwh_last_analyzed": None if right is None else right.get("last_analyzed"),
                "ofakim_count_error": None if left is None else left.get("count_error"),
                "dwh_count_error": None if right is None else right.get("count_error"),
            }
        )
    code_keys = sorted(set(source["code"]) | set(target["code"]))
    code = []
    for key in code_keys:
        left = source["code"].get(key)
        right = target["code"].get(key)
        basis = left or right
        code.append(
            {
                "schema": basis["owner"],
                "name": basis["name"],
                "type": basis["type"],
                "status": _code_status(left, right),
                "ofakim_lines": None if left is None else left.get("line_count"),
                "dwh_lines": None if right is None else right.get("line_count"),
            }
        )
    return {"tables": tables, "code": code}


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
    datapump_jobs = [
        {
            "owner": _text(owner),
            "job_name": _text(job_name),
            "operation": _text(operation),
            "job_mode": _text(job_mode),
            "state": _text(state),
        }
        for owner, job_name, operation, job_mode, state in query(DATAPUMP_SQL)
    ]
    return {
        "schemas": schemas,
        "top_tables": top_tables,
        "database_links": links,
        "materialized_views": materialized_views,
        "scheduler_jobs": jobs,
        "datapump_jobs": datapump_jobs,
        "query_errors": errors,
    }


def _mentions(value: str | None, aliases: list[str]) -> bool:
    text = (value or "").upper()
    return any(alias and alias.upper() in text for alias in aliases)


def compare_inventories(
    source: dict[str, Any],
    target: dict[str, Any],
    source_aliases: list[str],
    target_aliases: list[str],
) -> dict[str, Any]:
    """Classify schemas and the paths that can move data from source to target."""
    source_names = set(source["schemas"])
    target_names = set(target["schemas"])
    both = sorted(source_names & target_names)
    movement_markers = ("DBMS_DATAPUMP", "DBMS_MVIEW", "COPY_SCHEMA", "NETWORK_LINK", "MV_REFRESH")

    def matching_links(inventory: dict[str, Any], aliases: list[str]) -> list[dict[str, Any]]:
        return [link for link in inventory["database_links"] if _mentions(link.get("host"), aliases)]

    def matching_jobs(inventory: dict[str, Any], aliases: list[str]) -> list[dict[str, Any]]:
        matched = []
        for job in inventory["scheduler_jobs"]:
            action = f"{job.get('job_name') or ''} {job.get('job_action') or ''}"
            if _mentions(action, aliases) or _mentions(action, list(movement_markers)):
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
        "source_datapump_jobs": source["datapump_jobs"],
        "target_datapump_jobs": target["datapump_jobs"],
    }
