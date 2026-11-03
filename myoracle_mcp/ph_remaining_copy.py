"""Copy PH units the normal refresh left behind.

The refresh inserts a unit only when its serial is new and its RF number is
not already in ``ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES``. A listed product can
also be invisible when the name is stored as ``FIRST_UUT_NAME`` and the
unit's ``LAST_UUT_NAME`` is a different product. This copies those serials
and records them in ``TRANSFER_USER.TRANSFER_LOG``.
"""

from __future__ import annotations

UUT_COLUMNS = (
    "UUT_SERIAL_NUMBER", "RF_NUMBER", "FIRST_UUT_NAME", "FIRST_HARD_WARE_VERSION",
    "FIRST_TEST_DATE", "FIRST_TESTED_STATION_TYPE", "FIRST_UUT_STATUS", "FIRST_ATE_NUMBER",
    "FIRST_PRODUCTION_SITE", "LAST_UUT_NAME", "LAST_HARD_WARE_VERSION", "LAST_TEST_DATE",
    "LAST_TESTED_STATION_TYPE", "LAST_UUT_STATUS", "LAST_ATE_NUMBER", "LAST_PRODUCTION_SITE",
    "SONS_RF_SN_DELIM", "PARENT_RF_SN", "MAC_ADDRESS", "RFID_NUMBER", "UUT_SW", "IMEI",
    "GSM_MODULE_SN", "RF_MODULE_SN", "ADDITIONAL_ATTRIBUTES",
)

_COLUMN_LIST = ", ".join(UUT_COLUMNS)

_INSERT_REMAINING_MV = f"""
insert into ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES (ID, {_COLUMN_LIST})
select ATE_RESULTS.SEQ_GLOBAL_UUT_ATTRIBUTES.nextval, {_COLUMN_LIST}
from TRANSFER_USER.PH_UUT_ATTRUBUTES source
where not exists (
    select 1 from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES existing
    where existing.UUT_SERIAL_NUMBER = source.UUT_SERIAL_NUMBER
)
and not exists (
    select 1 from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES existing_rf
    where existing_rf.RF_NUMBER = source.RF_NUMBER
)
"""

_BLOCKED_BY_RF = """
select source.UUT_SERIAL_NUMBER, source.RF_NUMBER
from TRANSFER_USER.PH_UUT_ATTRUBUTES source
where not exists (
    select 1 from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES existing
    where existing.UUT_SERIAL_NUMBER = source.UUT_SERIAL_NUMBER
)
and exists (
    select 1 from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES existing_rf
    where existing_rf.RF_NUMBER = source.RF_NUMBER
)
order by source.UUT_SERIAL_NUMBER
"""

_INSERT_FIRST_NAME_ONLY = f"""
insert into ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES (ID, {_COLUMN_LIST})
select ATE_RESULTS.SEQ_GLOBAL_UUT_ATTRIBUTES.nextval, {_COLUMN_LIST}
from ATE_RESULTS.SITE_UUT_ATTRUBUTES@PH_DB source
where source.FIRST_UUT_NAME in (
    select products.LAST_UUT_NAME from ATE_RESULTS.TRANSFER_PRODUCTS@PH_DB products
)
and source.LAST_UUT_NAME not in (
    select products.LAST_UUT_NAME from ATE_RESULTS.TRANSFER_PRODUCTS@PH_DB products
)
and source.LAST_TEST_DATE > to_date('01-02-2022', 'DD-MM-YYYY')
and not exists (
    select 1 from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES existing
    where existing.UUT_SERIAL_NUMBER = source.UUT_SERIAL_NUMBER
)
"""

_LOG_NEW = """
insert into TRANSFER_USER.TRANSFER_LOG (UUT_SERIAL_NUMBER, SOURCE_SITE, T_DATE, T_STATUS)
select global_uut.UUT_SERIAL_NUMBER, 'PH', sysdate, 'T'
from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES global_uut
where global_uut.UUT_SERIAL_NUMBER in (
    select source.UUT_SERIAL_NUMBER from TRANSFER_USER.PH_UUT_ATTRUBUTES source
    union
    select source.UUT_SERIAL_NUMBER
    from ATE_RESULTS.SITE_UUT_ATTRUBUTES@PH_DB source
    where source.FIRST_UUT_NAME in (
        select products.LAST_UUT_NAME from ATE_RESULTS.TRANSFER_PRODUCTS@PH_DB products
    )
    and source.LAST_UUT_NAME not in (
        select products.LAST_UUT_NAME from ATE_RESULTS.TRANSFER_PRODUCTS@PH_DB products
    )
)
and not exists (
    select 1 from TRANSFER_USER.TRANSFER_LOG log
    where log.UUT_SERIAL_NUMBER = global_uut.UUT_SERIAL_NUMBER
)
"""

_INSERTED_SERIALS = """
select source.UUT_SERIAL_NUMBER
from TRANSFER_USER.PH_UUT_ATTRUBUTES source
where not exists (
    select 1 from TRANSFER_USER.TRANSFER_LOG log
    where log.UUT_SERIAL_NUMBER = source.UUT_SERIAL_NUMBER
)
and exists (
    select 1 from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES existing
    where existing.UUT_SERIAL_NUMBER = source.UUT_SERIAL_NUMBER
)
union
select source.UUT_SERIAL_NUMBER
from ATE_RESULTS.SITE_UUT_ATTRUBUTES@PH_DB source
where source.FIRST_UUT_NAME in (
    select products.LAST_UUT_NAME from ATE_RESULTS.TRANSFER_PRODUCTS@PH_DB products
)
and source.LAST_UUT_NAME not in (
    select products.LAST_UUT_NAME from ATE_RESULTS.TRANSFER_PRODUCTS@PH_DB products
)
and exists (
    select 1 from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES existing
    where existing.UUT_SERIAL_NUMBER = source.UUT_SERIAL_NUMBER
)
and not exists (
    select 1 from TRANSFER_USER.TRANSFER_LOG log
    where log.UUT_SERIAL_NUMBER = source.UUT_SERIAL_NUMBER
)
order by 1
"""


def copy_remaining_ph_units(cursor) -> dict[str, object]:
    """Insert PH serials the refresh skipped and log them as transferred."""
    cursor.execute(_INSERT_REMAINING_MV)
    from_materialized_view = int(cursor.rowcount or 0)
    cursor.execute(_BLOCKED_BY_RF)
    blocked_by_rf = [
        {"uut_serial_number": str(serial), "rf_number": None if rf_number is None else str(rf_number)}
        for serial, rf_number in cursor
    ]
    cursor.execute(_INSERT_FIRST_NAME_ONLY)
    from_first_name = int(cursor.rowcount or 0)
    cursor.execute(_INSERTED_SERIALS)
    serials = [str(row[0]) for row in cursor]
    cursor.execute(_LOG_NEW)
    logged = int(cursor.rowcount or 0)
    return {
        "inserted_from_materialized_view": from_materialized_view,
        "inserted_from_first_name": from_first_name,
        "logged": logged,
        "serials": serials,
        "blocked_by_existing_rf": blocked_by_rf,
    }
