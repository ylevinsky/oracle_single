"""Copy every overload of one packaged procedure onto another database."""

from __future__ import annotations

import re
from typing import Any, Callable

_IDENTIFIER = re.compile(r"[A-Z][A-Z0-9_$#]{0,127}")
_HEADER = re.compile(
    r"^\s*(?:PROCEDURE|FUNCTION)\s+([A-Za-z][A-Za-z0-9_$#]*)",
    re.IGNORECASE,
)


def normalize_identifier(value: str, label: str) -> str:
    name = str(value or "").strip().upper()
    if not _IDENTIFIER.fullmatch(name):
        raise ValueError(f"{label} must be a simple Oracle identifier")
    return name


def member_span(lines: list[str], procedure_name: str) -> tuple[int, int]:
    """Return the line slice covering every overload of one procedure."""
    name = procedure_name.upper()
    headers = [
        (index, match.group(1).upper())
        for index, line in enumerate(lines)
        if (match := _HEADER.match(line))
    ]
    wanted = [index for index, header in headers if header == name]
    if not wanted:
        raise ValueError(f"procedure {procedure_name} was not found")
    between = [header for index, header in headers if wanted[0] <= index <= wanted[-1]]
    if any(header != name for header in between):
        raise ValueError(f"procedure {procedure_name} overloads are not contiguous")
    following = [index for index, _header in headers if index > wanted[-1]]
    end = following[0] if following else len(lines)
    return wanted[0], end


def replace_overloads(
    target_lines: list[str], source_lines: list[str], procedure_name: str
) -> tuple[list[str], int]:
    """Replace the target overloads with every source overload."""
    target_start, target_end = member_span(target_lines, procedure_name)
    source_start, source_end = member_span(source_lines, procedure_name)
    replacement = source_lines[source_start:source_end]
    merged = target_lines[:target_start] + replacement + target_lines[target_end:]
    return merged, source_end - source_start


def package_statement(owner: str, package_name: str, object_type: str, lines: list[str]) -> str:
    """Build one CREATE OR REPLACE statement for a package spec or body."""
    body = "".join(lines).strip()
    kind = "PACKAGE BODY" if object_type == "PACKAGE BODY" else "PACKAGE"
    body = re.sub(
        rf"^(?:{kind})\s+\"?[A-Za-z][A-Za-z0-9_$#]*\"?",
        f'{kind} "{owner}"."{package_name}"',
        body,
        count=1,
        flags=re.IGNORECASE,
    )
    statement = "CREATE OR REPLACE " + body
    if not statement.endswith(";"):
        statement += ";"
    return statement


class _Database:
    def __init__(self, name: str, connect: Callable[[str], Any]) -> None:
        self.name = name
        self._connect = connect
        self._connection: Any = None

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def connection(self) -> Any:
        if self._connection is None:
            self._connection = self._connect(self.name)
            self._connection.call_timeout = 600_000
        return self._connection

    def lines(self, owner: str, package_name: str, object_type: str) -> list[str]:
        with self.connection().cursor() as cursor:
            cursor.execute(
                "select text from dba_source "
                "where owner = :owner and name = :name and type = :object_type order by line",
                {"owner": owner, "name": package_name, "object_type": object_type},
            )
            rows = [str(row[0]) for row in cursor]
        if not rows:
            raise ValueError(f"{self.name} has no {owner}.{package_name} {object_type}")
        return rows

    def execute(self, statement: str) -> None:
        with self.connection().cursor() as cursor:
            cursor.execute(statement)
        self.connection().commit()

    def overload_count(self, owner: str, package_name: str, procedure_name: str) -> int:
        with self.connection().cursor() as cursor:
            cursor.execute(
                "select count(*) from all_procedures "
                "where owner = :owner and object_name = :package_name "
                "and procedure_name = :procedure_name",
                {
                    "owner": owner,
                    "package_name": package_name,
                    "procedure_name": procedure_name,
                },
            )
            return int(cursor.fetchone()[0])

    def object_status(self, owner: str, object_name: str, object_type: str) -> str | None:
        with self.connection().cursor() as cursor:
            cursor.execute(
                "select status from dba_objects "
                "where owner = :owner and object_name = :object_name and object_type = :object_type",
                {"owner": owner, "object_name": object_name, "object_type": object_type},
            )
            row = cursor.fetchone()
        return None if row is None else str(row[0])

    def error_text(self, owner: str, object_name: str) -> str | None:
        with self.connection().cursor() as cursor:
            cursor.execute(
                "select text from dba_errors where owner = :owner and name = :name and rownum = 1",
                {"owner": owner, "name": object_name},
            )
            row = cursor.fetchone()
        return None if row is None else " ".join(str(row[0]).split())


def sync_overloads(
    source_name: str,
    target_name: str,
    owner: str,
    package_name: str,
    procedure_name: str,
    *,
    confirmed: bool,
    connect: Callable[[str], Any],
    trigger_owner: str | None = None,
    trigger_name: str | None = None,
) -> dict[str, Any]:
    """Replace one target procedure with every source overload and compile a trigger."""
    if source_name == target_name:
        raise ValueError("source and target connections must be different")
    safe_owner = normalize_identifier(owner, "owner")
    safe_package = normalize_identifier(package_name, "package_name")
    safe_procedure = normalize_identifier(procedure_name, "procedure_name")
    safe_trigger_owner = (
        normalize_identifier(trigger_owner, "trigger_owner") if trigger_owner else None
    )
    safe_trigger = normalize_identifier(trigger_name, "trigger_name") if trigger_name else None
    if (safe_trigger_owner is None) != (safe_trigger is None):
        raise ValueError("trigger_owner and trigger_name must be supplied together")
    source = _Database(source_name, connect)
    target = _Database(target_name, connect)
    try:
        before = target.overload_count(safe_owner, safe_package, safe_procedure)
        source_count = source.overload_count(safe_owner, safe_package, safe_procedure)
        if not confirmed:
            return {
                "status": "not_confirmed",
                "source": source_name,
                "target": target_name,
                "package": f"{safe_owner}.{safe_package}",
                "procedure": safe_procedure,
                "source_overloads": source_count,
                "target_overloads": before,
            }
        for object_type in ("PACKAGE", "PACKAGE BODY"):
            merged, _copied = replace_overloads(
                target.lines(safe_owner, safe_package, object_type),
                source.lines(safe_owner, safe_package, object_type),
                safe_procedure,
            )
            target.execute(package_statement(safe_owner, safe_package, object_type, merged))
        package_status = target.object_status(safe_owner, safe_package, "PACKAGE BODY")
        after = target.overload_count(safe_owner, safe_package, safe_procedure)
        trigger_status = None
        trigger_error = None
        if safe_trigger and safe_trigger_owner:
            target.execute(
                f'alter trigger "{safe_trigger_owner}"."{safe_trigger}" compile'
            )
            trigger_status = target.object_status(safe_trigger_owner, safe_trigger, "TRIGGER")
            if trigger_status != "VALID":
                trigger_error = target.error_text(safe_trigger_owner, safe_trigger)
        status = "synced"
        if package_status != "VALID" or (trigger_status is not None and trigger_status != "VALID"):
            status = "synced_with_errors"
        return {
            "status": status,
            "source": source_name,
            "target": target_name,
            "package": f"{safe_owner}.{safe_package}",
            "procedure": safe_procedure,
            "source_overloads": source_count,
            "target_overloads_before": before,
            "target_overloads": after,
            "package_body_status": package_status,
            "trigger": None if safe_trigger is None else f"{safe_trigger_owner}.{safe_trigger}",
            "trigger_status": trigger_status,
            "trigger_error": trigger_error,
        }
    finally:
        source.close()
        target.close()
