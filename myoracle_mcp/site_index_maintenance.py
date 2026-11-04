"""Apply standard site index recommendations on saved Oracle connections."""

from __future__ import annotations

import re
from typing import Any, Callable

IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]{0,29}$")
TEST_OWNER = re.compile(
    r"(^TEST|TEST$|_TEST|_TST$|^.*_TST$|TST_|^FOG_TST$|^TEST_)",
    re.IGNORECASE,
)

NUMERIC_ARRAY_COLUMNS = (
    "CONFIG_ID",
    "TEST_ID",
    "ARRAY_NAME",
    "ARRAY_ORDER",
    "INPUT_ORDER",
)

UNINDEXED_FK_SQL = """
SELECT c.owner, c.table_name, cc.column_name AS fk_column
FROM dba_constraints c
JOIN dba_cons_columns cc
  ON cc.owner = c.owner
 AND cc.constraint_name = c.constraint_name
 AND cc.position = 1
JOIN dba_users u
  ON u.username = c.owner
 AND u.oracle_maintained = 'N'
WHERE c.constraint_type = 'R'
  AND c.status = 'ENABLED'
  AND NOT EXISTS (
    SELECT 1
    FROM dba_ind_columns ic
    JOIN dba_indexes i
      ON i.owner = ic.index_owner
     AND i.index_name = ic.index_name
    WHERE ic.table_owner = c.owner
      AND ic.table_name = c.table_name
      AND ic.column_position = 1
      AND ic.column_name = cc.column_name
      AND i.index_type NOT LIKE 'LOB%'
      AND i.status = 'VALID'
  )
ORDER BY c.owner, c.table_name
"""

STATION_SCHEMAS_SQL = """
SELECT DISTINCT t.owner
FROM dba_tables t
JOIN dba_users u ON u.username = t.owner AND u.oracle_maintained = 'N'
WHERE t.table_name IN ('STEP_RESULT', 'UUT_RESULT', 'SETTING_NUMERIC_ARRAY')
GROUP BY t.owner
HAVING COUNT(DISTINCT t.table_name) = 3
ORDER BY t.owner
"""


def _quote_owner(owner: str) -> str:
    if IDENTIFIER.fullmatch(owner):
        return owner.upper()
    return f'"{owner.upper()}"'


def _quote_table(table_name: str) -> str:
    return table_name.upper()


def _quote_index(index_name: str) -> str:
    return index_name.upper()


def _identical_index_exists(cursor: Any, owner: str, table_name: str, columns: list[str]) -> bool:
    cursor.execute(
        "SELECT index_name FROM dba_indexes "
        "WHERE table_owner = :owner AND table_name = :table_name AND index_type = 'NORMAL'",
        {"owner": owner.upper(), "table_name": table_name.upper()},
    )
    expected = [(column.upper(), "ASC") for column in columns]
    index_names = [str(row[0]) for row in cursor]
    for index_name in index_names:
        cursor.execute(
            "SELECT column_name, descend FROM dba_ind_columns "
            "WHERE index_owner = :owner AND index_name = :index_name "
            "ORDER BY column_position",
            {"owner": owner.upper(), "index_name": index_name},
        )
        existing = [(str(row[0]), str(row[1])) for row in cursor]
        if existing == expected:
            return True
    return False


def _index_name_exists(cursor: Any, owner: str, index_name: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM dba_indexes WHERE owner = :owner AND index_name = :index_name",
        {"owner": owner.upper(), "index_name": index_name.upper()},
    )
    return cursor.fetchone() is not None


def _table_exists(cursor: Any, owner: str, table_name: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM dba_tables WHERE owner = :owner AND table_name = :table_name",
        {"owner": owner.upper(), "table_name": table_name.upper()},
    )
    return cursor.fetchone() is not None


def _make_fk_index_name(table_name: str, fk_column: str) -> str:
    raw = f"IDX_{table_name}_{fk_column}"
    if len(raw) <= 30:
        return raw.upper()
    trimmed = f"IDX_{table_name[:18]}_{fk_column[:8]}"
    return trimmed[:30].upper()


def _make_schema_tag(owner: str) -> str:
    tag = re.sub(r"[^A-Z0-9]", "", owner.upper())[:10]
    return tag or "SCH"


def _create_index(
    cursor: Any,
    owner: str,
    table_name: str,
    index_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    if _identical_index_exists(cursor, owner, table_name, columns):
        raise ValueError(
            f"Identical index already exists on {owner.upper()}.{table_name.upper()}"
        )
    if _index_name_exists(cursor, owner, index_name):
        raise ValueError(f"Index name {owner.upper()}.{index_name.upper()} already exists")
    kind = "UNIQUE INDEX" if unique else "INDEX"
    column_list = ", ".join(_quote_table(column) for column in columns)
    base_sql = (
        f"CREATE {kind} {_quote_owner(owner)}.{_quote_index(index_name)} "
        f"ON {_quote_owner(owner)}.{_quote_table(table_name)} ({column_list})"
    )
    cursor.execute(f"{base_sql} ONLINE")


def _should_skip_owner(owner: str, skip_test_owners: bool) -> bool:
    if owner.upper() in {"SHAY"}:
        return True
    if skip_test_owners and TEST_OWNER.search(owner):
        return True
    return False


def _run_index_ddl(
    connect: Callable[[str], Any],
    connection_name: str,
    owner: str,
    table_name: str,
    index_name: str,
    columns: list[str],
    *,
    unique: bool,
) -> None:
    """Open a fresh session, create one index if needed, and close."""
    connection = connect(connection_name)
    try:
        with connection.cursor() as cursor:
            if not _table_exists(cursor, owner, table_name):
                raise ValueError(f"Table {owner.upper()}.{table_name.upper()} does not exist")
            _create_index(
                cursor,
                owner,
                table_name,
                index_name,
                columns,
                unique=unique,
            )
    finally:
        connection.close()


def apply_proposed_site_indexes(
    connection_name: str,
    confirmed: bool,
    connect: Callable[[str], Any],
    *,
    skip_test_owners: bool = True,
) -> dict[str, object]:
    """Create missing FK, station, hub, and report indexes from the site checklist."""
    if not confirmed:
        raise ValueError("confirmed must be true after explicit approval for this write operation.")

    created: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    work: list[tuple[str, str, str, str, list[str], bool]] = []

    connection = connect(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(STATION_SCHEMAS_SQL)
            station_owners = [str(row[0]) for row in cursor]

            for owner in station_owners:
                if _should_skip_owner(owner, skip_test_owners):
                    continue
                tag = _make_schema_tag(owner)
                for table_name, index_name, columns, unique in (
                    ("STEP_RESULT", f"IDX_{tag}_SR_PARENTS", ["STEP_PARENT"], False),
                    (
                        "UUT_RESULT",
                        f"IDX_{tag}_UUT_SN_START",
                        ["UUT_SERIAL_NUMBER", "START_DATE_TIME"],
                        False,
                    ),
                    (
                        "SETTING_NUMERIC_ARRAY",
                        "NUMERIC_ARRAY_DUPLICATED_ROW",
                        list(NUMERIC_ARRAY_COLUMNS),
                        True,
                    ),
                ):
                    if _table_exists(cursor, owner, table_name):
                        work.append(
                            ("station_template", owner, table_name, index_name, columns, unique)
                        )

            for owner, table_name, index_name, columns, unique in (
                (
                    "ATE_RESULTS",
                    "TRANSFER_PRODUCTS_QUEUE",
                    "IDX_TPQ_LAST_UUT",
                    ["LAST_UUT_NAME"],
                    False,
                ),
                (
                    "ATE_RESULTS",
                    "TRANSFER_PRODUCTS_QUEUE",
                    "IDX_TPQ_TIME_STAMP",
                    ["TIME_STAMP"],
                    False,
                ),
                (
                    "ATE_RESULTS",
                    "TRANSFER_PRODUCTS_LOG",
                    "IDX_TPL_TIME_STAMP",
                    ["TIME_STAMP"],
                    False,
                ),
                (
                    "ATE_RESULTS",
                    "SITE_UUT_ATT_UPDATES",
                    "IDX_SITE_ATT_UPD_SN",
                    ["SN"],
                    False,
                ),
                (
                    "ATE_RESULTS",
                    "SITE_UUT_ATT_UPDATES",
                    "IDX_SITE_ATT_UPD_START",
                    ["START_DATE_TIME"],
                    False,
                ),
                (
                    "ATE_REPORTS",
                    "TBL_OOBA_ROWS",
                    "IDX_TBL_OOBA_ROWS_ID",
                    ["ID"],
                    True,
                ),
                (
                    "ATE_REPORTS",
                    "TBL_OOBA_ROWS",
                    "IDX_OOBA_ROWS_OOBA_ID",
                    ["OOBA_ID"],
                    False,
                ),
                (
                    "ATE_REPORTS",
                    "TBL_OOBA_ROWS",
                    "IDX_OOBA_ROWS_SN",
                    ["UUT_SERIAL_NUMBER"],
                    False,
                ),
            ):
                if _table_exists(cursor, owner, table_name):
                    work.append(("hub_report", owner, table_name, index_name, columns, unique))

            cursor.execute(UNINDEXED_FK_SQL)
            for owner_s, table_s, fk_s in cursor:
                if _should_skip_owner(str(owner_s), skip_test_owners):
                    continue
                work.append(
                    (
                        "foreign_key",
                        str(owner_s),
                        str(table_s),
                        _make_fk_index_name(str(table_s), str(fk_s)),
                        [str(fk_s)],
                        False,
                    )
                )
    finally:
        connection.close()

    for kind, owner, table_name, index_name, columns, unique in work:
        try:
            _run_index_ddl(
                connect,
                connection_name,
                owner,
                table_name,
                index_name,
                columns,
                unique=unique,
            )
            created.append(
                {
                    "owner": owner.upper(),
                    "table_name": table_name,
                    "index_name": index_name.upper(),
                    "kind": kind,
                }
            )
        except ValueError as exc:
            skipped.append(
                {
                    "owner": owner.upper(),
                    "table_name": table_name,
                    "index_name": index_name.upper(),
                    "reason": str(exc),
                }
            )
        except Exception as exc:  # pragma: no cover - live Oracle errors
            errors.append(
                {
                    "owner": owner.upper(),
                    "table_name": table_name,
                    "index_name": index_name.upper(),
                    "error": str(exc),
                }
            )

    return {
        "connection_name": connection_name,
        "created_count": len(created),
        "skipped_count": len(skipped),
        "error_count": len(errors),
        "created": created[:200],
        "skipped": skipped[:200],
        "errors": errors[:100],
        "truncated": {
            "created": len(created) > 200,
            "skipped": len(skipped) > 200,
            "errors": len(errors) > 100,
        },
    }
