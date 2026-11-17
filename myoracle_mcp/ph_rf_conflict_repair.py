"""Resolve one PH RF collision using the PH refresh materialized view as source."""

from __future__ import annotations

from hungary_targeted_copy import UUT_COLUMNS
from site_backlog import SITE_STAGING_TABLES

_COLUMN_LIST = ", ".join(UUT_COLUMNS)


def repair_ph_rf_conflict(
    cursor,
    source_serial: str,
    stale_target_serial: str,
    rf_number: str,
) -> dict[str, object]:
    """Move one RF from an orphaned global row to its verified PH source row.

    The older global row is retained with a NULL RF. Its serial must be absent
    from every current site staging MV, and the PH MV must contain exactly one
    source row for the requested serial/RF pair. Both global uniqueness keys
    are checked before the update and the source row insert.
    """
    if not all(isinstance(value, str) and value.strip() for value in
               (source_serial, stale_target_serial, rf_number)):
        raise ValueError("source_serial, stale_target_serial, and rf_number are required.")
    if source_serial == stale_target_serial:
        raise ValueError("Source and stale target serials must differ.")

    cursor.execute(
        "select count(*) from TRANSFER_USER.PH_UUT_ATTRUBUTES "
        "where UUT_SERIAL_NUMBER = :serial and RF_NUMBER = :rf",
        serial=source_serial,
        rf=rf_number,
    )
    if int(cursor.fetchone()[0]) != 1:
        raise ValueError("PH staging must contain exactly one row for the source serial/RF pair.")

    cursor.execute(
        "select count(*) from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES "
        "where UUT_SERIAL_NUMBER = :serial",
        serial=source_serial,
    )
    source_target_count = int(cursor.fetchone()[0])
    if source_target_count:
        cursor.execute(
            "select count(*) from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES "
            "where UUT_SERIAL_NUMBER = :serial and RF_NUMBER = :rf",
            serial=source_serial,
            rf=rf_number,
        )
        if int(cursor.fetchone()[0]) == 1:
            return {"status": "already_aligned", "source_serial": source_serial, "rf_number": rf_number}
        raise ValueError("The PH source serial already exists in the target with a different RF number.")

    cursor.execute(
        "select UUT_SERIAL_NUMBER, RF_NUMBER, FIRST_TEST_DATE, LAST_TEST_DATE "
        "from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES where RF_NUMBER = :rf",
        rf=rf_number,
    )
    conflict_rows = list(cursor.fetchall())
    if len(conflict_rows) != 1 or str(conflict_rows[0][0]) != stale_target_serial:
        raise ValueError("The target RF conflict no longer matches the supplied stale serial.")
    stale_row = conflict_rows[0]

    current_source_hits: list[str] = []
    for site, table in SITE_STAGING_TABLES.items():
        cursor.execute(
            f"select count(*) from TRANSFER_USER.{table} where UUT_SERIAL_NUMBER = :serial",
            serial=stale_target_serial,
        )
        if int(cursor.fetchone()[0]):
            current_source_hits.append(site)
    if current_source_hits:
        raise ValueError(
            "The stale target serial still appears in current site staging: "
            + ", ".join(current_source_hits)
        )

    cursor.execute(
        "update ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES set RF_NUMBER = null "
        "where UUT_SERIAL_NUMBER = :serial and RF_NUMBER = :rf",
        serial=stale_target_serial,
        rf=rf_number,
    )
    if int(cursor.rowcount or 0) != 1:
        raise RuntimeError("The conflicting target RF row changed during reconciliation.")

    cursor.execute(
        f"insert into ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES (ID, {_COLUMN_LIST}) "
        f"select ATE_RESULTS.SEQ_GLOBAL_UUT_ATTRIBUTES.nextval, {_COLUMN_LIST} "
        "from TRANSFER_USER.PH_UUT_ATTRUBUTES "
        "where UUT_SERIAL_NUMBER = :serial and RF_NUMBER = :rf",
        serial=source_serial,
        rf=rf_number,
    )
    if int(cursor.rowcount or 0) != 1:
        raise RuntimeError("The verified PH source row was not inserted into the global target.")

    cursor.execute(
        "insert into TRANSFER_USER.TRANSFER_LOG "
        "(UUT_SERIAL_NUMBER, SOURCE_SITE, T_DATE, T_STATUS) "
        "select :serial, 'PH', sysdate, 'T' from dual "
        "where not exists (select 1 from TRANSFER_USER.TRANSFER_LOG "
        "where UUT_SERIAL_NUMBER = :serial)",
        serial=source_serial,
    )
    logged = int(cursor.rowcount or 0)
    return {
        "status": "reconciled",
        "source_site": "PH",
        "source_serial": source_serial,
        "rf_number": rf_number,
        "previous_target_serial": stale_target_serial,
        "previous_target_rf_cleared": True,
        "previous_target_first_test_date": str(stale_row[2]) if stale_row[2] is not None else None,
        "previous_target_last_test_date": str(stale_row[3]) if stale_row[3] is not None else None,
        "transfer_log_rows_added": logged,
    }
