"""Copy explicitly listed Hungary units the normal refresh left behind.

The Hungary refresh inserts a unit only when its product is present in the
remote ``ATE_RESULTS.TRANSFER_PRODUCTS_QUEUE`` and its RF number is not
already in ``ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES``. When the queue is drained
or a scheduled run is missed, staged rows sit in
``TRANSFER_USER.HUNGARY_UUT_ATTRUBUTES`` without reaching the global table.
This copies only the requested RF numbers (no full-product backfill) and
records them in ``TRANSFER_USER.TRANSFER_LOG`` with source ``Hungary``.
Serials (``HUNGARY_NKEYS_ALLOCATED``) are out of scope and left to the
normal refresh.
"""

from __future__ import annotations

import re

UUT_COLUMNS = (
    "UUT_SERIAL_NUMBER", "RF_NUMBER", "FIRST_UUT_NAME", "FIRST_HARD_WARE_VERSION",
    "FIRST_TEST_DATE", "FIRST_TESTED_STATION_TYPE", "FIRST_UUT_STATUS", "FIRST_ATE_NUMBER",
    "FIRST_PRODUCTION_SITE", "LAST_UUT_NAME", "LAST_HARD_WARE_VERSION", "LAST_TEST_DATE",
    "LAST_TESTED_STATION_TYPE", "LAST_UUT_STATUS", "LAST_ATE_NUMBER", "LAST_PRODUCTION_SITE",
    "SONS_RF_SN_DELIM", "PARENT_RF_SN", "MAC_ADDRESS", "RFID_NUMBER", "UUT_SW", "IMEI",
    "GSM_MODULE_SN", "RF_MODULE_SN", "ADDITIONAL_ATTRIBUTES",
)

_COLUMN_LIST = ", ".join(UUT_COLUMNS)
_UPDATE_COLUMNS = ", ".join(UUT_COLUMNS[1:])

_RF_PATTERN = re.compile(r"[A-Za-z0-9]{1,64}")
_MAX_RF = 100
_SITE = "Hungary"


def normalize_rf_numbers(rf_numbers: list[str]) -> list[str]:
    """Strip, uppercase, dedupe, and validate requested RF numbers."""
    if not isinstance(rf_numbers, list) or not rf_numbers:
        raise ValueError("rf_numbers must be a non-empty list of RF numbers.")
    if len(rf_numbers) > _MAX_RF:
        raise ValueError(f"rf_numbers holds at most {_MAX_RF} values.")
    cleaned: list[str] = []
    for value in rf_numbers:
        text = str(value).strip().upper()
        if not _RF_PATTERN.fullmatch(text):
            raise ValueError(f"Invalid RF_NUMBER: {value!r}.")
        if text not in cleaned:
            cleaned.append(text)
    if not cleaned:
        raise ValueError("rf_numbers must be a non-empty list of RF numbers.")
    return cleaned


def _placeholders(rf_numbers: list[str]) -> str:
    return ", ".join(f":rf{i}" for i in range(len(rf_numbers)))


def _binds(rf_numbers: list[str]) -> dict[str, str]:
    return {f"rf{i}": rf for i, rf in enumerate(rf_numbers)}


def copy_hungary_units_by_rf(cursor, rf_numbers: list[str]) -> dict[str, object]:
    """Insert listed Hungary RF numbers into the Spain global table and log them."""
    rf_list = normalize_rf_numbers(rf_numbers)
    placeholders = _placeholders(rf_list)
    binds = _binds(rf_list)

    cursor.execute(
        f"insert into ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES (ID, {_COLUMN_LIST}) "
        f"select ATE_RESULTS.SEQ_GLOBAL_UUT_ATTRIBUTES.nextval, {_COLUMN_LIST} "
        f"from TRANSFER_USER.HUNGARY_UUT_ATTRUBUTES source "
        f"where source.RF_NUMBER in ({placeholders}) "
        "and not exists (select 1 from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES existing "
        "where existing.UUT_SERIAL_NUMBER = source.UUT_SERIAL_NUMBER) "
        "and not exists (select 1 from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES existing_rf "
        "where existing_rf.RF_NUMBER = source.RF_NUMBER)",
        binds,
    )
    inserted = int(cursor.rowcount or 0)

    cursor.execute(
        f"select source.RF_NUMBER from TRANSFER_USER.HUNGARY_UUT_ATTRUBUTES source "
        f"where source.RF_NUMBER in ({placeholders})",
        binds,
    )
    found = [str(row[0]).strip().upper() for row in cursor]
    missing_in_source = [rf for rf in rf_list if rf not in found]

    cursor.execute(
        f"select source.UUT_SERIAL_NUMBER, source.RF_NUMBER "
        f"from TRANSFER_USER.HUNGARY_UUT_ATTRUBUTES source "
        f"where source.RF_NUMBER in ({placeholders}) "
        "and not exists (select 1 from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES existing "
        "where existing.UUT_SERIAL_NUMBER = source.UUT_SERIAL_NUMBER) "
        "and exists (select 1 from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES existing_rf "
        "where existing_rf.RF_NUMBER = source.RF_NUMBER)",
        binds,
    )
    blocked_by_rf = [
        {"uut_serial_number": str(serial), "rf_number": str(rf)}
        for serial, rf in cursor
    ]

    cursor.execute(
        f"select source.UUT_SERIAL_NUMBER from TRANSFER_USER.HUNGARY_UUT_ATTRUBUTES source "
        f"where source.RF_NUMBER in ({placeholders}) "
        "and not exists (select 1 from TRANSFER_USER.TRANSFER_LOG log "
        "where log.UUT_SERIAL_NUMBER = source.UUT_SERIAL_NUMBER) "
        "and exists (select 1 from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES existing "
        "where existing.UUT_SERIAL_NUMBER = source.UUT_SERIAL_NUMBER)",
        binds,
    )
    serials = [str(row[0]) for row in cursor]

    cursor.execute(
        f"insert into TRANSFER_USER.TRANSFER_LOG (UUT_SERIAL_NUMBER, SOURCE_SITE, T_DATE, T_STATUS) "
        f"select global_uut.UUT_SERIAL_NUMBER, '{_SITE}', sysdate, 'T' "
        f"from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES global_uut "
        f"where global_uut.RF_NUMBER in ({placeholders}) "
        "and not exists (select 1 from TRANSFER_USER.TRANSFER_LOG log "
        "where log.UUT_SERIAL_NUMBER = global_uut.UUT_SERIAL_NUMBER)",
        binds,
    )
    logged = int(cursor.rowcount or 0)

    cursor.execute(
        f"update ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES global_uut "
        f"set ({_UPDATE_COLUMNS}) = "
        f"(select {_UPDATE_COLUMNS} from TRANSFER_USER.HUHGARY_UUT_ATTRIBUTES_UPDATE source "
        "where source.UUT_SERIAL_NUMBER = global_uut.UUT_SERIAL_NUMBER) "
        f"where global_uut.RF_NUMBER in ({placeholders}) "
        "and exists (select 1 from TRANSFER_USER.HUHGARY_UUT_ATTRIBUTES_UPDATE source "
        "where source.UUT_SERIAL_NUMBER = global_uut.UUT_SERIAL_NUMBER)",
        binds,
    )
    updated = int(cursor.rowcount or 0)

    cursor.execute(
        f"insert into TRANSFER_USER.TRANSFER_LOG (UUT_SERIAL_NUMBER, SOURCE_SITE, T_DATE, T_STATUS) "
        f"select global_uut.UUT_SERIAL_NUMBER, '{_SITE}', sysdate, 'R' "
        f"from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES global_uut "
        f"join TRANSFER_USER.HUHGARY_UUT_ATTRIBUTES_UPDATE source "
        "on source.UUT_SERIAL_NUMBER = global_uut.UUT_SERIAL_NUMBER "
        "where not exists (select 1 from TRANSFER_USER.TRANSFER_LOG log "
        "where log.UUT_SERIAL_NUMBER = global_uut.UUT_SERIAL_NUMBER)",
        None,
    )
    update_logged = int(cursor.rowcount or 0)

    return {
        "rf_numbers": rf_list,
        "inserted": inserted,
        "logged": logged,
        "serials": serials,
        "updated": updated,
        "update_logged": update_logged,
        "blocked_by_existing_rf": blocked_by_rf,
        "missing_in_source": missing_in_source,
    }


def copy_hungary_remaining_units(cursor) -> dict[str, object]:
    """Insert every Hungary MV row missing from the Spain global table and log it.

    No RF filter and no queue gate: any row in
    ``TRANSFER_USER.HUNGARY_UUT_ATTRUBUTES`` whose serial and RF number are
    both absent from ``ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES`` is copied, then
    recorded in ``TRANSFER_USER.TRANSFER_LOG`` with source ``Hungary``.
    Matching update-view rows refresh the global row (status ``R``).
    Serials (``HUNGARY_NKEYS_ALLOCATED``) are out of scope.
    """
    cursor.execute(
        f"insert into ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES (ID, {_COLUMN_LIST}) "
        f"select ATE_RESULTS.SEQ_GLOBAL_UUT_ATTRIBUTES.nextval, {_COLUMN_LIST} "
        f"from TRANSFER_USER.HUNGARY_UUT_ATTRUBUTES source "
        "where not exists (select 1 from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES existing "
        "where existing.UUT_SERIAL_NUMBER = source.UUT_SERIAL_NUMBER) "
        "and not exists (select 1 from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES existing_rf "
        "where existing_rf.RF_NUMBER = source.RF_NUMBER)"
    )
    inserted = int(cursor.rowcount or 0)

    cursor.execute(
        "select count(*) from TRANSFER_USER.HUNGARY_UUT_ATTRUBUTES source "
        "where not exists (select 1 from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES existing "
        "where existing.UUT_SERIAL_NUMBER = source.UUT_SERIAL_NUMBER) "
        "and exists (select 1 from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES existing_rf "
        "where existing_rf.RF_NUMBER = source.RF_NUMBER)"
    )
    blocked_count_row = cursor.fetchone()
    blocked_count = int(blocked_count_row[0]) if blocked_count_row else 0

    cursor.execute(
        "insert into TRANSFER_USER.TRANSFER_LOG (UUT_SERIAL_NUMBER, SOURCE_SITE, T_DATE, T_STATUS) "
        f"select source.UUT_SERIAL_NUMBER, '{_SITE}', sysdate, 'T' "
        "from TRANSFER_USER.HUNGARY_UUT_ATTRUBUTES source "
        "join ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES global_uut "
        "on global_uut.UUT_SERIAL_NUMBER = source.UUT_SERIAL_NUMBER "
        "where not exists (select 1 from TRANSFER_USER.TRANSFER_LOG log "
        "where log.UUT_SERIAL_NUMBER = source.UUT_SERIAL_NUMBER)"
    )
    logged = int(cursor.rowcount or 0)

    cursor.execute(
        f"update ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES global_uut "
        f"set ({_UPDATE_COLUMNS}) = "
        f"(select {_UPDATE_COLUMNS} from TRANSFER_USER.HUHGARY_UUT_ATTRIBUTES_UPDATE source "
        "where source.UUT_SERIAL_NUMBER = global_uut.UUT_SERIAL_NUMBER) "
        "where exists (select 1 from TRANSFER_USER.HUHGARY_UUT_ATTRIBUTES_UPDATE source "
        "where source.UUT_SERIAL_NUMBER = global_uut.UUT_SERIAL_NUMBER)"
    )
    updated = int(cursor.rowcount or 0)

    cursor.execute(
        "insert into TRANSFER_USER.TRANSFER_LOG (UUT_SERIAL_NUMBER, SOURCE_SITE, T_DATE, T_STATUS) "
        f"select global_uut.UUT_SERIAL_NUMBER, '{_SITE}', sysdate, 'R' "
        "from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES global_uut "
        "join TRANSFER_USER.HUHGARY_UUT_ATTRIBUTES_UPDATE source "
        "on source.UUT_SERIAL_NUMBER = global_uut.UUT_SERIAL_NUMBER "
        "where not exists (select 1 from TRANSFER_USER.TRANSFER_LOG log "
        "where log.UUT_SERIAL_NUMBER = global_uut.UUT_SERIAL_NUMBER)"
    )
    update_logged = int(cursor.rowcount or 0)

    return {
        "inserted": inserted,
        "logged": logged,
        "updated": updated,
        "update_logged": update_logged,
        "blocked_by_existing_rf": blocked_count,
    }
