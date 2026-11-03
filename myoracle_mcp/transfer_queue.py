"""Queue table for pending TRANSFER_PRODUCTS rows.

TRANSFER_PRODUCTS_LOG stays an insert-only history. TRANSFER_PRODUCTS_QUEUE
holds the rows still waiting for a refresh, and the insert trigger writes both.
"""

from __future__ import annotations

OWNER = "ATE_RESULTS"
SOURCE_TABLE = "TRANSFER_PRODUCTS"
LOG_TABLE = "TRANSFER_PRODUCTS_LOG"
QUEUE_TABLE = "TRANSFER_PRODUCTS_QUEUE"
NEW_TRIGGER_NAME = "TRG_TP_INS_QUEUE"


def ensure_transfer_products_queue(cursor) -> dict[str, object]:
    """Create the queue table and point the insert trigger at the log and the queue."""
    source = _require_source_table(cursor)
    columns = _source_columns(cursor)
    queue_created = _create_queue_if_missing(cursor, columns)
    backfilled = _backfill_queue_from_log(cursor, columns) if queue_created else 0
    trigger_name = _replace_insert_trigger(cursor, columns)
    return {
        "source_table": source,
        "log_table": f"{OWNER}.{LOG_TABLE}",
        "queue_table": f"{OWNER}.{QUEUE_TABLE}",
        "queue_created": queue_created,
        "backfilled_rows": backfilled,
        "trigger": f"{OWNER}.{trigger_name}",
        "trigger_status": _trigger_status(cursor, trigger_name),
        "status": "ready",
    }


def _require_source_table(cursor) -> str:
    cursor.execute(
        "select object_type from dba_objects where owner = :owner and object_name = :name",
        {"owner": OWNER, "name": SOURCE_TABLE},
    )
    row = cursor.fetchone()
    if row is None or str(row[0]).upper() != "TABLE":
        raise ValueError(f"Source table {OWNER}.{SOURCE_TABLE} was not found.")
    return f"{OWNER}.{SOURCE_TABLE}"


def _source_columns(cursor) -> list[str]:
    cursor.execute(
        "select column_name from dba_tab_columns where owner = :owner and table_name = :table_name "
        "order by column_id",
        {"owner": OWNER, "table_name": SOURCE_TABLE},
    )
    columns = [str(column).upper() for column, in cursor]
    if not columns:
        raise ValueError(f"Source table {OWNER}.{SOURCE_TABLE} has no usable columns.")
    return columns


def _create_queue_if_missing(cursor, columns: list[str]) -> bool:
    cursor.execute(
        "select object_type from dba_objects where owner = :owner and object_name = :name",
        {"owner": OWNER, "name": QUEUE_TABLE},
    )
    row = cursor.fetchone()
    if row is not None:
        if str(row[0]).upper() != "TABLE":
            raise ValueError(f"{OWNER}.{QUEUE_TABLE} exists and is not a table.")
        return False
    column_list = ", ".join(columns)
    cursor.execute(
        f"create table {OWNER}.{QUEUE_TABLE} as "
        f"select {column_list} from {OWNER}.{SOURCE_TABLE} where 1 = 0"
    )
    cursor.execute(
        f"alter table {OWNER}.{QUEUE_TABLE} add "
        "(TIME_STAMP TIMESTAMP WITH TIME ZONE default SYSTIMESTAMP not null)"
    )
    return True


def _backfill_queue_from_log(cursor, columns: list[str]) -> int:
    cursor.execute(
        "select count(*) from dba_tables where owner = :owner and table_name = :name",
        {"owner": OWNER, "name": LOG_TABLE},
    )
    if int(cursor.fetchone()[0]) == 0:
        return 0
    column_list = ", ".join([*columns, "TIME_STAMP"])
    cursor.execute(
        f"insert into {OWNER}.{QUEUE_TABLE} ({column_list}) "
        f"select {column_list} from {OWNER}.{LOG_TABLE}"
    )
    return int(cursor.rowcount or 0)


def _replace_insert_trigger(cursor, columns: list[str]) -> str:
    cursor.execute(
        "select trigger_name from dba_triggers "
        "where table_owner = :owner and table_name = :table_name "
        "order by trigger_name",
        {"owner": OWNER, "table_name": SOURCE_TABLE},
    )
    names = [str(name).upper() for name, in cursor]
    if len(names) > 1:
        raise ValueError(f"{OWNER}.{SOURCE_TABLE} has more than one trigger: {names}.")
    trigger_name = names[0] if names else NEW_TRIGGER_NAME
    column_list = ", ".join(columns)
    new_values = ", ".join(f":new.{column}" for column in columns)
    cursor.execute(
        f"create or replace trigger {OWNER}.{trigger_name} "
        f"after insert on {OWNER}.{SOURCE_TABLE} for each row "
        "begin "
        f"insert into {OWNER}.{LOG_TABLE} ({column_list}) values ({new_values}); "
        f"insert into {OWNER}.{QUEUE_TABLE} ({column_list}) values ({new_values}); "
        "end;"
    )
    return trigger_name


_MISSING_PRODUCTS = f"""
select p.last_uut_name
from {OWNER}.{SOURCE_TABLE} p
where not exists (
    select 1 from {OWNER}.{QUEUE_TABLE} q
    where q.last_uut_name = p.last_uut_name
)
and not exists (
    select 1 from {OWNER}.{LOG_TABLE} l
    where l.last_uut_name = p.last_uut_name
)
order by p.last_uut_name
"""


def enqueue_unlogged_products(cursor) -> dict[str, object]:
    """Write product names the insert trigger never saw into the log and the queue.

    The AFTER INSERT trigger copies ``LAST_UUT_NAME`` into both tables. Names
    already stored in ``TRANSFER_PRODUCTS`` before that trigger existed are
    absent from both. This performs those same two inserts and leaves names
    that are already logged or queued untouched.
    """
    cursor.execute(_MISSING_PRODUCTS)
    names = [str(row[0]) for row in cursor]
    if not names:
        return {"logged": 0, "queued": 0, "products": []}
    cursor.executemany(
        f"insert into {OWNER}.{LOG_TABLE} (LAST_UUT_NAME) values (:name)",
        [{"name": name} for name in names],
    )
    logged = int(cursor.rowcount or 0)
    cursor.executemany(
        f"insert into {OWNER}.{QUEUE_TABLE} (LAST_UUT_NAME) values (:name)",
        [{"name": name} for name in names],
    )
    queued = int(cursor.rowcount or 0)
    return {"logged": logged, "queued": queued, "products": names}


def _trigger_status(cursor, trigger_name: str) -> str | None:
    cursor.execute(
        "select status from dba_triggers where owner = :owner and trigger_name = :trigger_name",
        {"owner": OWNER, "trigger_name": trigger_name},
    )
    row = cursor.fetchone()
    return str(row[0]) if row else None
