"""Create the Repair Center objects used by the Philippines refresh worker."""

from __future__ import annotations

import re
from typing import Any, Callable

REPAIR_CENTER_CONNECTION = "es_db2_orclsp_sys"
OWNER = "TRANSFER_USER"
TABLESPACE = "SPAIN_TBS"
PROCEDURE_NAME = "CREATE_PH_REFRESH_MVIEWS"

UUT_COLUMNS = """
    "ID" NUMBER,
    "UUT_SERIAL_NUMBER" VARCHAR2(255) NOT NULL ENABLE,
    "RF_NUMBER" VARCHAR2(255),
    "FIRST_UUT_NAME" VARCHAR2(255),
    "FIRST_HARD_WARE_VERSION" VARCHAR2(255),
    "FIRST_TEST_DATE" DATE,
    "FIRST_TESTED_STATION_TYPE" VARCHAR2(255),
    "FIRST_UUT_STATUS" VARCHAR2(255),
    "FIRST_ATE_NUMBER" NUMBER,
    "FIRST_PRODUCTION_SITE" VARCHAR2(20),
    "LAST_UUT_NAME" VARCHAR2(255),
    "LAST_HARD_WARE_VERSION" VARCHAR2(255),
    "LAST_TEST_DATE" DATE,
    "LAST_TESTED_STATION_TYPE" VARCHAR2(255),
    "LAST_UUT_STATUS" VARCHAR2(255),
    "LAST_ATE_NUMBER" NUMBER,
    "LAST_PRODUCTION_SITE" VARCHAR2(20),
    "SONS_RF_SN_DELIM" VARCHAR2(200 CHAR),
    "PARENT_RF_SN" VARCHAR2(20),
    "MAC_ADDRESS" VARCHAR2(255),
    "RFID_NUMBER" VARCHAR2(255),
    "UUT_SW" VARCHAR2(256),
    "IMEI" VARCHAR2(256),
    "GSM_MODULE_SN" VARCHAR2(255),
    "RF_MODULE_SN" VARCHAR2(255),
    "ADDITIONAL_ATTRIBUTES" VARCHAR2(200 CHAR),
    "PRODUCTION_STATUS" VARCHAR2(20 CHAR),
    "PACKING_STATUS" VARCHAR2(40 CHAR),
    "FIRST_WORK_ORDER" VARCHAR2(20 CHAR),
    "LAST_WORK_ORDER" VARCHAR2(20 CHAR),
    "LAST_STATION_CODE" VARCHAR2(40 CHAR),
    "REBOUND_COUNT" NUMBER,
    "PARENT_SN" VARCHAR2(40 CHAR),
    "ACCOUNT_ID" VARCHAR2(100),
    "CCSN" VARCHAR2(100),
    "PHONE_NUMBER" VARCHAR2(100),
    "CCID" VARCHAR2(100),
    "UDI" VARCHAR2(100)
"""

UUT_SELECT = """
SELECT "ID", "UUT_SERIAL_NUMBER", "RF_NUMBER", "FIRST_UUT_NAME", "FIRST_HARD_WARE_VERSION",
       "FIRST_TEST_DATE", "FIRST_TESTED_STATION_TYPE", "FIRST_UUT_STATUS", "FIRST_ATE_NUMBER",
       "FIRST_PRODUCTION_SITE", "LAST_UUT_NAME", "LAST_HARD_WARE_VERSION", "LAST_TEST_DATE",
       "LAST_TESTED_STATION_TYPE", "LAST_UUT_STATUS", "LAST_ATE_NUMBER", "LAST_PRODUCTION_SITE",
       "SONS_RF_SN_DELIM", "PARENT_RF_SN", "MAC_ADDRESS", "RFID_NUMBER", "UUT_SW", "IMEI",
       "GSM_MODULE_SN", "RF_MODULE_SN", "ADDITIONAL_ATTRIBUTES", "PRODUCTION_STATUS",
       "PACKING_STATUS", "FIRST_WORK_ORDER", "LAST_WORK_ORDER", "LAST_STATION_CODE",
       "REBOUND_COUNT", "PARENT_SN", "ACCOUNT_ID", "CCSN", "PHONE_NUMBER", "CCID", "UDI"
  FROM VW_TRANSFER_SITE_UUT_ATTRIBUTES@PH_DB remote
"""

MVIEW_QUERIES = {
    "PH_UUT_ATTRUBUTES": UUT_SELECT + """
 WHERE UUT_SERIAL_NUMBER NOT IN (
       SELECT UUT_SERIAL_NUMBER FROM TRANSFER_USER.TRANSFER_LOG)
""",
    "PH_UUT_ATTRIBUTES_UPDATE": UUT_SELECT + """
 WHERE EXISTS (
       SELECT 1
         FROM ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES
        WHERE uut_serial_number = remote.uut_serial_number
          AND LAST_TEST_DATE < remote.LAST_TEST_DATE)
""",
    "PH_NKEYS_ALLOCATED": """
SELECT *
  FROM SERIAL_NUMBER.NKEYS_ALLOCATED@PH_DB remote
 WHERE NOT EXISTS (
       SELECT 1
         FROM TRANSFER_USER.TRANSFER_LOG_SERIAL log
        WHERE log.PCB_SN = remote.PCB_SN)
""",
}

TABLE_SQL = {
    "PH_UUT_ATTRUBUTES": f"create table {OWNER}.PH_UUT_ATTRUBUTES ({UUT_COLUMNS}) tablespace {TABLESPACE}",
    "PH_UUT_ATTRIBUTES_UPDATE": f"create table {OWNER}.PH_UUT_ATTRIBUTES_UPDATE ({UUT_COLUMNS}) tablespace {TABLESPACE}",
    "PH_NKEYS_ALLOCATED": f"""
        create table {OWNER}.PH_NKEYS_ALLOCATED (
            "ALLOCATION_ID" NUMBER,
            "ALLOCATION_DATE" DATE,
            "PRODUCT_NAME" VARCHAR2(30 CHAR),
            "PCB_SN" VARCHAR2(16 CHAR),
            "NODEID" VARCHAR2(8 CHAR),
            "CRYPT_KEY" VARCHAR2(32 CHAR),
            "HASH_KEY" VARCHAR2(32 CHAR),
            "LABEL" VARCHAR2(10 CHAR),
            "MACADDR" VARCHAR2(12 CHAR)
        ) tablespace {TABLESPACE}
    """,
}

INDEX_NAME = "IDX_PH_UUT_ATTRUBUTES_1SN"
INDEX_SQL = (
    f"create index {OWNER}.{INDEX_NAME} on {OWNER}.PH_UUT_ATTRUBUTES "
    f"(UUT_SERIAL_NUMBER) tablespace {TABLESPACE}"
)


def mview_statement(name: str) -> str:
    return f"""
        create materialized view {OWNER}.{name}
        on prebuilt table without reduced precision
        using index
        refresh force on demand
        using default local rollback segment
        using enforced constraints disable query rewrite
        as
        {MVIEW_QUERIES[name]}
    """


def procedure_source() -> str:
    statements = "\n".join(
        f"""
        select count(*) into existing_count from user_mviews where mview_name = '{name}';
        if existing_count = 0 then
            execute immediate q'[{mview_statement(name)}]';
        end if;
        """
        for name in MVIEW_QUERIES
    )
    return f"""
        create or replace procedure {OWNER}.{PROCEDURE_NAME} authid definer as
            existing_count number;
        begin
            {statements}
        end;
    """


def summarize_philippines_transfer(connect: Callable[[str], Any], started_at: str) -> dict[str, Any]:
    """Count Philippines rows copied into Spain since a timestamp."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", started_at):
        raise ValueError("started_at must be YYYY-MM-DD HH:MM:SS.")
    connection = connect(REPAIR_CENTER_CONNECTION)
    try:
        connection.call_timeout = 60_000
        with connection.cursor() as cursor:
            cursor.execute(
                "select t_status, count(*) from transfer_user.transfer_log "
                "where source_site = 'PH' and t_date >= to_date(:started_at, 'YYYY-MM-DD HH24:MI:SS') "
                "group by t_status order by t_status",
                {"started_at": started_at},
            )
            uut_rows = [{"status": str(status), "rows": int(count)} for status, count in cursor]
            cursor.execute(
                "select t_status, count(*) from transfer_user.transfer_log_serial "
                "where source_site = 'PH' and t_date >= to_date(:started_at, 'YYYY-MM-DD HH24:MI:SS') "
                "group by t_status order by t_status",
                {"started_at": started_at},
            )
            serial_rows = [{"status": str(status), "rows": int(count)} for status, count in cursor]
            cursor.execute(
                "select mview_name, to_char(last_refresh_date, 'YYYY-MM-DD HH24:MI:SS') "
                "from dba_mviews where owner = 'TRANSFER_USER' and mview_name like 'PH%' "
                "order by mview_name"
            )
            views = [
                {"name": str(name), "last_refresh_date": str(refreshed) if refreshed else None}
                for name, refreshed in cursor
            ]
        return {
            "since": started_at,
            "uut_transfer_rows": uut_rows,
            "serial_transfer_rows": serial_rows,
            "materialized_views": views,
        }
    finally:
        connection.close()


def unlock_ate_results(confirmed: bool, connect: Callable[[str], Any]) -> dict[str, Any]:
    """Unlock the Philippines ATE_RESULTS account after failed link logons."""
    if not confirmed:
        raise ValueError("confirmed must be true after explicit approval for this write operation.")
    connection = connect("PH")
    try:
        connection.call_timeout = 60_000
        with connection.cursor() as cursor:
            cursor.execute("alter user ATE_RESULTS account unlock")
            cursor.execute(
                "select account_status, profile from dba_users where username = 'ATE_RESULTS'"
            )
            status, profile = cursor.fetchone()
            cursor.execute(
                "select limit from dba_profiles "
                "where profile = :profile and resource_name = 'FAILED_LOGIN_ATTEMPTS'",
                {"profile": str(profile)},
            )
            limit_row = cursor.fetchone()
        return {
            "username": "ATE_RESULTS",
            "account_status": str(status),
            "profile": str(profile),
            "failed_login_attempts": str(limit_row[0]) if limit_row else None,
        }
    finally:
        connection.close()


def describe_refresh_access(connect: Callable[[str], Any]) -> dict[str, Any]:
    """Return the Philippines view dependencies and whether the link can read it."""
    spain = connect(REPAIR_CENTER_CONNECTION)
    philippines = None
    try:
        spain.call_timeout = 90_000
        with spain.cursor() as cursor:
            cursor.execute(
                "select mview_name, compile_state from dba_mviews "
                "where owner = :owner and mview_name in "
                "('PH_UUT_ATTRUBUTES', 'PH_UUT_ATTRIBUTES_UPDATE', 'PH_NKEYS_ALLOCATED') "
                "order by mview_name",
                {"owner": OWNER},
            )
            mviews = [
                {"name": str(name), "compile_state": str(state) if state else None}
                for name, state in cursor
            ]
            cursor.execute(
                "select owner, object_name, object_type, status from dba_objects "
                "where object_name in "
                "('PH_UUT_ATTRUBUTES', 'PH_UUT_ATTRIBUTES_UPDATE', 'PH_NKEYS_ALLOCATED') "
                "order by owner, object_name, object_type"
            )
            objects = [
                {
                    "owner": str(owner),
                    "name": str(name),
                    "type": str(object_type),
                    "status": str(status),
                }
                for owner, name, object_type, status in cursor
            ]
            cursor.execute(
                "create or replace procedure mcp_probe_ph_view authid definer as "
                "n number; begin select count(*) into n from "
                "ate_results.vw_transfer_site_uut_attributes@ph_db where rownum < 2; end;"
            )
            cursor.execute(
                "select text from dba_errors where name = 'MCP_PROBE_PH_VIEW' order by sequence"
            )
            view_errors = [str(text).strip() for (text,) in cursor if text]
            view_ok = False
            view_runtime_error = None
            if not view_errors:
                try:
                    cursor.execute("begin mcp_probe_ph_view; end;")
                    view_ok = True
                except Exception as exc:
                    view_runtime_error = str(exc).splitlines()[0][:500]
            cursor.execute("drop procedure mcp_probe_ph_view")
        philippines = connect("PH")
        philippines.call_timeout = 60_000
        with philippines.cursor() as cursor:
            cursor.execute(
                "select referenced_owner, referenced_name, referenced_type "
                "from dba_dependencies where owner = 'ATE_RESULTS' "
                "and name = 'VW_TRANSFER_SITE_UUT_ATTRIBUTES' and type = 'VIEW' "
                "order by referenced_owner, referenced_name"
            )
            dependencies = [
                {"owner": str(owner), "name": str(name), "type": str(object_type)}
                for owner, name, object_type in cursor
            ]
            grants = []
            for item in dependencies:
                cursor.execute(
                    "select privilege from dba_tab_privs "
                    "where grantee = 'ATE_RESULTS' and owner = :owner and table_name = :name "
                    "order by privilege",
                    {"owner": item["owner"], "name": item["name"]},
                )
                privileges = [str(privilege) for (privilege,) in cursor]
                grants.append({**item, "ate_results_privileges": privileges, "owned": item["owner"] == "ATE_RESULTS"})
        return {
            "materialized_views": mviews,
            "objects": objects,
            "remote_view_readable": view_ok,
            "remote_view_compile_error": view_errors[0][:500] if view_errors else None,
            "remote_view_runtime_error": view_runtime_error,
            "view_dependencies": grants,
        }
    finally:
        spain.close()
        if philippines is not None:
            philippines.close()


def create_objects(
    connection_name: str,
    confirmed: bool,
    connect: Callable[[str], Any],
) -> dict[str, Any]:
    """Create missing Philippines refresh tables, index, and materialized views."""
    if connection_name != REPAIR_CENTER_CONNECTION:
        raise ValueError(
            "Philippines refresh objects are created only on the Repair Center "
            f"connection {REPAIR_CENTER_CONNECTION}."
        )
    if not confirmed:
        raise ValueError("confirmed must be true after explicit approval for this write operation.")

    connection = connect(connection_name)
    created_tables: list[str] = []
    created_index = False
    created_mviews: list[str] = []
    procedure_created = False
    try:
        connection.call_timeout = 120_000
        with connection.cursor() as cursor:
            for name, statement in TABLE_SQL.items():
                if _missing(cursor, "dba_tables", name):
                    cursor.execute(statement)
                    created_tables.append(name)
            if _missing_index(cursor):
                cursor.execute(INDEX_SQL)
                created_index = True
            before = _existing_mviews(cursor)
            cursor.execute(procedure_source())
            procedure_created = True
            cursor.execute(f"begin {OWNER}.{PROCEDURE_NAME}; end;")
            created_mviews = [name for name in MVIEW_QUERIES if name not in before and name in _existing_mviews(cursor)]
        return {
            "connection": connection_name,
            "owner": OWNER,
            "created_tables": created_tables,
            "created_index": INDEX_NAME if created_index else None,
            "created_materialized_views": created_mviews,
            "status": "created",
        }
    finally:
        if procedure_created:
            with connection.cursor() as cursor:
                cursor.execute(f"drop procedure {OWNER}.{PROCEDURE_NAME}")
        connection.close()


def _missing(cursor: Any, view_name: str, object_name: str) -> bool:
    cursor.execute(
        f"select count(*) from {view_name} where owner = :owner and table_name = :object_name",
        owner=OWNER,
        object_name=object_name,
    )
    return int(cursor.fetchone()[0]) == 0


def _missing_index(cursor: Any) -> bool:
    cursor.execute(
        "select count(*) from dba_indexes where owner = :owner and index_name = :index_name",
        owner=OWNER,
        index_name=INDEX_NAME,
    )
    return int(cursor.fetchone()[0]) == 0


def _existing_mviews(cursor: Any) -> set[str]:
    cursor.execute(
        "select mview_name from dba_mviews where owner = :owner and mview_name in "
        "('PH_UUT_ATTRUBUTES', 'PH_UUT_ATTRIBUTES_UPDATE', 'PH_NKEYS_ALLOCATED')",
        owner=OWNER,
    )
    return {str(row[0]) for row in cursor}
