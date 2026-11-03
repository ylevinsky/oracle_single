"""Force one site's TRANSFER_USER refresh from the Spain Repair Center.

Mirrors one ``refresh_mv.py`` site worker (refresh, copy UUTs, copy
serials, audit record) but with the gates bypassed: no queue membership
check, no cooldown, no skip. The caller connects as the saved Spain SYSDBA
record; the materialized views pull from the site through their own links.
"""

from __future__ import annotations

from datetime import datetime

from hungary_targeted_copy import _COLUMN_LIST, _UPDATE_COLUMNS

SITES = {
    "Hungary": ("HUNGARY_UUT_ATTRUBUTES", "HUHGARY_UUT_ATTRIBUTES_UPDATE", "HUNGARY_NKEYS_ALLOCATED", "Hungary"),
    "Ofakim": ("OFAKIM_UUT_ATTRUBUTES_1", "OFAKIM_UUT_ATTRIBUTES_UPDATE", "OFAKIM_NKEYS_ALLOCATED", "Ofakim"),
    "RH": ("RH_UUT_ATTRUBUTES", "RH_UUT_ATTRIBUTES_UPDATE", "RH_NKEYS_ALLOCATED", "RH"),
    "PH": ("PH_UUT_ATTRUBUTES", "PH_UUT_ATTRIBUTES_UPDATE", "PH_NKEYS_ALLOCATED", "PH"),
}

_MAX_ERROR_CHARS = 4000


def _log_procedure(cursor, site: str, state: str, started_at, input_text: str | None, output_text: str | None) -> None:
    safe_input = input_text[:4000] if input_text else None
    safe_output = output_text[:_MAX_ERROR_CHARS] if output_text else None
    cursor.execute(
        "insert into TRANSFER_USER.LOG_PROCEDURE values "
        "('DAILY_TRANSFER', :state, :started_at, :ended_at, :input_text, :output_text, null, 'DAILY_TRANSFER')",
        state=state, started_at=started_at, ended_at=datetime.now(),
        input_text=safe_input, output_text=safe_output,
    )


def force_site_refresh(cursor, site: str) -> dict[str, object]:
    """Refresh one site's views and copy everything the run produced."""
    if site not in SITES:
        raise ValueError(f"Unknown site {site!r}. Choose one of {sorted(SITES)}.")
    source_view, update_view, serial_view, site_label = SITES[site]
    started_at = datetime.now()
    refreshed: list[dict[str, object]] = []
    try:
        cursor.execute(
            "begin dbms_application_info.set_module(:module, :action); end;",
            module="DAILY_TRANSFER_PY", action=site,
        )
        for view_name in (source_view, update_view, serial_view):
            cursor.execute(
                "begin dbms_mview.refresh(:view_name, method => 'C', atomic_refresh => false); end;",
                view_name=f"TRANSFER_USER.{view_name}",
            )
            cursor.execute(
                "begin dbms_stats.gather_table_stats(ownname => 'TRANSFER_USER', tabname => :view_name, "
                "cascade => true, no_invalidate => false); end;",
                view_name=view_name,
            )
            cursor.execute(f"alter materialized view TRANSFER_USER.{view_name} compile")
            cursor.connection.commit()
            refreshed.append({"view": view_name, "status": "refreshed"})

        cursor.execute(
            f"insert into ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES (ID, {_COLUMN_LIST}) "
            f"select ATE_RESULTS.SEQ_GLOBAL_UUT_ATTRIBUTES.nextval, {_COLUMN_LIST} "
            f"from TRANSFER_USER.{source_view} source "
            "where not exists (select 1 from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES existing "
            "where existing.UUT_SERIAL_NUMBER = source.UUT_SERIAL_NUMBER) "
            "and not exists (select 1 from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES existing_rf "
            "where existing_rf.RF_NUMBER = source.RF_NUMBER)"
        )
        inserted = int(cursor.rowcount or 0)

        cursor.execute(
            "insert into TRANSFER_USER.TRANSFER_LOG (UUT_SERIAL_NUMBER, SOURCE_SITE, T_DATE, T_STATUS) "
            f"select source.UUT_SERIAL_NUMBER, '{site_label}', sysdate, 'T' "
            f"from TRANSFER_USER.{source_view} source "
            "join ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES global_uut "
            "on global_uut.UUT_SERIAL_NUMBER = source.UUT_SERIAL_NUMBER "
            "where not exists (select 1 from TRANSFER_USER.TRANSFER_LOG log "
            "where log.UUT_SERIAL_NUMBER = source.UUT_SERIAL_NUMBER)"
        )
        logged = int(cursor.rowcount or 0)

        cursor.execute(
            f"update ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES global_uut "
            f"set ({_UPDATE_COLUMNS}) = "
            f"(select {_UPDATE_COLUMNS} from TRANSFER_USER.{update_view} source "
            "where source.UUT_SERIAL_NUMBER = global_uut.UUT_SERIAL_NUMBER) "
            f"where exists (select 1 from TRANSFER_USER.{update_view} source "
            "where source.UUT_SERIAL_NUMBER = global_uut.UUT_SERIAL_NUMBER)"
        )
        updated = int(cursor.rowcount or 0)

        cursor.execute(
            "insert into TRANSFER_USER.TRANSFER_LOG (UUT_SERIAL_NUMBER, SOURCE_SITE, T_DATE, T_STATUS) "
            f"select source.UUT_SERIAL_NUMBER, '{site_label}', sysdate, 'R' "
            f"from TRANSFER_USER.{update_view} source "
            "join ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES global_uut "
            "on global_uut.UUT_SERIAL_NUMBER = source.UUT_SERIAL_NUMBER "
            "where not exists (select 1 from TRANSFER_USER.TRANSFER_LOG log "
            "where log.UUT_SERIAL_NUMBER = source.UUT_SERIAL_NUMBER)"
        )
        update_logged = int(cursor.rowcount or 0)

        cursor.execute(
            f"insert into SERIAL_NUMBER.NKEYS_ALLOCATED "
            f"select * from TRANSFER_USER.{serial_view} source where rownum < 100001 and not exists "
            "(select 1 from TRANSFER_USER.TRANSFER_LOG_SERIAL log where log.PCB_SN = source.PCB_SN)"
        )
        serials_inserted = int(cursor.rowcount or 0)

        cursor.execute(
            "insert into TRANSFER_USER.TRANSFER_LOG_SERIAL (PCB_SN, SOURCE_SITE, T_DATE, T_STATUS) "
            f"select source.PCB_SN, '{site_label}', sysdate, 'T' "
            f"from TRANSFER_USER.{serial_view} source "
            "join SERIAL_NUMBER.NKEYS_ALLOCATED allocated "
            "on allocated.PCB_SN = source.PCB_SN "
            "where not exists (select 1 from TRANSFER_USER.TRANSFER_LOG_SERIAL log "
            "where log.PCB_SN = source.PCB_SN)"
        )
        serials_logged = int(cursor.rowcount or 0)

        _log_procedure(cursor, site, "End", started_at, f"{site}:Ok;", None)
        return {
            "site": site,
            "refreshed": refreshed,
            "inserted": inserted,
            "logged": logged,
            "updated": updated,
            "update_logged": update_logged,
            "serials_inserted": serials_inserted,
            "serials_logged": serials_logged,
        }
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"[:_MAX_ERROR_CHARS]
        try:
            _log_procedure(cursor, site, "Error", started_at, f"{site}:", detail)
            cursor.connection.commit()
        except Exception:
            pass
        raise