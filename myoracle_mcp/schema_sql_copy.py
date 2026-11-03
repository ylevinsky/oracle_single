"""Copy one schema with DBMS_METADATA and row inserts.

This path does not use Data Pump, so it does not depend on the target
database timezone-file version. It stops before any change when the schema
already exists on the target.
"""

from __future__ import annotations

import re
from typing import Any, Callable

_IDENTIFIER = re.compile(r"[A-Z][A-Z0-9_$#]{0,127}")
_HASH = re.compile(r"[A-Z0-9:;$.]+")
_PRIVILEGE = re.compile(r"[A-Z][A-Z_ ]{0,30}")
_METADATA = {
    "SEQUENCE": "SEQUENCE",
    "TABLE": "TABLE",
    "INDEX": "INDEX",
    "VIEW": "VIEW",
    "FUNCTION": "FUNCTION",
    "PACKAGE": "PACKAGE",
    "PACKAGE BODY": "PACKAGE_BODY",
    "TRIGGER": "TRIGGER",
}
_CREATE_ORDER = ("SEQUENCE", "TABLE", "INDEX", "VIEW", "FUNCTION", "PACKAGE", "PACKAGE BODY", "TRIGGER")


def normalize_schema(schema_name: str) -> str:
    """Return one uppercase schema name, or raise when it is unsafe."""
    name = str(schema_name or "").strip().upper()
    if not _IDENTIFIER.fullmatch(name):
        raise ValueError("schema_name must be a simple Oracle identifier")
    return name


def normalize_remap(tablespace_remap: dict[str, str] | None) -> dict[str, str]:
    """Return uppercase tablespace remaps, or raise when a name is unsafe."""
    remap: dict[str, str] = {}
    for old, new in (tablespace_remap or {}).items():
        source = str(old or "").strip().upper()
        target = str(new or "").strip().upper()
        if not _IDENTIFIER.fullmatch(source) or not _IDENTIFIER.fullmatch(target):
            raise ValueError("tablespace_remap keys and values must be simple Oracle identifiers")
        remap[source] = target
    return remap


def remap_ddl(ddl: str, tablespace_remap: dict[str, str]) -> str:
    """Replace quoted tablespace names in one DDL statement."""
    text = str(ddl or "").strip().rstrip(";").strip()
    text = re.sub(r"\bPCTUSED\s+\d+\b", "", text, flags=re.IGNORECASE)
    for old, new in tablespace_remap.items():
        text = text.replace(f'"{old}"', f'"{new}"')
    return text


def qualify_trigger(ddl: str, schema: str) -> str:
    """Point the trigger's ON clause at the schema being copied.

    A SYS session otherwise resolves the unqualified table name in SYS.
    """
    return re.sub(
        r"(\bON\s+)(?!\")([A-Z][A-Z0-9_$#]*)\b(?!\s*\.)",
        lambda match: f'{match.group(1)}"{schema}"."{match.group(2).upper()}"',
        ddl,
        count=1,
        flags=re.IGNORECASE,
    )


def sql_statements(ddl: str, split_mode: str = "table") -> list[str]:
    """Split a metadata extract into executable statements.

    Table metadata glues the table, its index, and the primary-key alter
    together. PL/SQL is kept whole, except a trailing ``ALTER TRIGGER``.
    """
    text = str(ddl or "").strip()
    if split_mode == "trigger":
        chunks = re.split(r"\n(?=\s*ALTER\s+TRIGGER\b)", text, flags=re.IGNORECASE)
    elif split_mode == "table":
        if re.search(r"\b(?:SEGMENT CREATION|TABLESPACE)\b", text, re.IGNORECASE):
            text = re.sub(r"[ \t]+(?=(?:CREATE|ALTER)\b)", "\n", text, flags=re.IGNORECASE)
        chunks = re.split(r"\n(?=\s*(?:CREATE|ALTER|COMMENT|GRANT)\b)", text)
    else:
        chunks = [text]
    statements: list[str] = []
    plsql = split_mode in {"plsql", "trigger"}
    for chunk in chunks:
        piece = chunk.strip()
        if not piece:
            continue
        if plsql and re.match(r"CREATE\b", piece, re.IGNORECASE):
            if not piece.endswith(";"):
                piece += ";"
        else:
            piece = piece.rstrip(";").strip()
        if not piece:
            continue
        if statements and not re.match(r"(CREATE|ALTER|COMMENT|GRANT)\b", piece, re.IGNORECASE):
            statements[-1] = statements[-1] + "\n" + piece
        else:
            statements.append(piece)
    return statements


def _text(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "read"):
        data = value.read()
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace")
        return str(data)
    return str(value)


def _cell(value: Any) -> Any:
    if hasattr(value, "read"):
        return value.read()
    return value


def _safe(message: str, secret: str) -> str:
    if secret and secret in message:
        return message.replace(secret, "***")
    return message


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
            self._connection.call_timeout = 1_800_000
        return self._connection

    def query(self, sql: str, binds: dict[str, Any] | None = None) -> list[tuple]:
        with self.connection().cursor() as cursor:
            cursor.execute(sql, binds or {})
            return list(cursor.fetchall())

    def call(self, sql: str, binds: dict[str, Any] | None = None) -> None:
        with self.connection().cursor() as cursor:
            cursor.execute(sql, binds or {})
        self.connection().commit()


def _exists(database: _Database, schema: str) -> bool:
    rows = database.query(
        "select username from dba_users where username = :schema",
        {"schema": schema},
    )
    return bool(rows)


def _hash(database: _Database, schema: str) -> str:
    rows = database.query("select spare4 from sys.user$ where name = :schema", {"schema": schema})
    if not rows or not rows[0][0]:
        raise ValueError(f"{schema} has no password verifier on the source")
    verifier = str(rows[0][0]).strip()
    if not _HASH.fullmatch(verifier):
        raise ValueError(f"{schema} password verifier has an unexpected form")
    return verifier


def _configure_metadata(database: _Database) -> None:
    database.call(
        """
        begin
          dbms_metadata.set_transform_param(dbms_metadata.session_transform, 'SQLTERMINATOR', false);
          dbms_metadata.set_transform_param(dbms_metadata.session_transform, 'PRETTY', false);
          dbms_metadata.set_transform_param(dbms_metadata.session_transform, 'STORAGE', false);
          dbms_metadata.set_transform_param(dbms_metadata.session_transform, 'SEGMENT_ATTRIBUTES', true);
          dbms_metadata.set_transform_param(dbms_metadata.session_transform, 'TABLESPACE', true);
          dbms_metadata.set_transform_param(dbms_metadata.session_transform, 'CONSTRAINTS', true);
          dbms_metadata.set_transform_param(dbms_metadata.session_transform, 'REF_CONSTRAINTS', false);
          dbms_metadata.set_transform_param(dbms_metadata.session_transform, 'EMIT_SCHEMA', true);
        end;
        """
    )


def _plsql_ddl(database: _Database, object_type: str, object_name: str, schema: str) -> str:
    rows = database.query(
        "select text from dba_source where owner = :schema and name = :name and type = :object_type order by line",
        {"schema": schema, "name": object_name, "object_type": object_type},
    )
    body = "".join(str(row[0]) for row in rows).strip()
    statement = re.sub(
        rf"^(PACKAGE BODY|PACKAGE|FUNCTION|TRIGGER)\s+(?!\"{schema}\"\.)",
        lambda match: f'{match.group(1)} "{schema}".',
        body,
        count=1,
        flags=re.IGNORECASE,
    )
    if not statement.upper().startswith("CREATE"):
        statement = "CREATE OR REPLACE " + statement
    if not statement.endswith(";"):
        statement += ";"
    return statement


def _ddl(database: _Database, object_type: str, object_name: str, schema: str) -> str:
    rows = database.query(
        "select dbms_metadata.get_ddl(:object_type, :object_name, :schema) from dual",
        {"object_type": _METADATA[object_type], "object_name": object_name, "schema": schema},
    )
    return _text(rows[0][0] if rows else "")


def _objects(database: _Database, schema: str) -> list[tuple[str, str]]:
    rows = database.query(
        "select object_type, object_name from dba_objects "
        "where owner = :schema and object_type in "
        "('SEQUENCE','TABLE','INDEX','VIEW','FUNCTION','PACKAGE','PACKAGE BODY','TRIGGER') "
        "and object_name not like 'BIN$%' and object_name not like 'SYS\\_%' escape '\\' "
        "order by object_type, object_name",
        {"schema": schema},
    )
    return [(str(object_type), str(object_name)) for object_type, object_name in rows]


def _constraint_indexes(database: _Database, schema: str) -> set[str]:
    rows = database.query(
        "select index_name from dba_constraints "
        "where owner = :schema and index_name is not null",
        {"schema": schema},
    )
    return {str(name) for name, in rows}


def _temporary_tables(database: _Database, schema: str) -> set[str]:
    rows = database.query(
        "select table_name from dba_tables where owner = :schema and temporary = 'Y'",
        {"schema": schema},
    )
    return {str(name) for name, in rows}


def _ref_constraints(database: _Database, schema: str) -> list[str]:
    rows = database.query(
        "select constraint_name from dba_constraints "
        "where owner = :schema and constraint_type = 'R' order by constraint_name",
        {"schema": schema},
    )
    return [str(name) for name, in rows]


def _grants(database: _Database, schema: str) -> list[tuple[str, str, str]]:
    rows = database.query(
        "select grantee, privilege, table_name from dba_tab_privs "
        "where owner = :schema order by grantee, table_name, privilege",
        {"schema": schema},
    )
    return [(str(grantee), str(privilege), str(table_name)) for grantee, privilege, table_name in rows]


def _grantee_exists(database: _Database, grantee: str) -> bool:
    rows = database.query(
        "select username from dba_users where username = :name "
        "union all select role from dba_roles where role = :name",
        {"name": grantee},
    )
    return bool(rows)


def _copy_rows(source: _Database, target: _Database, schema: str, table: str) -> int:
    with source.connection().cursor() as read_cursor:
        read_cursor.execute(f'select * from "{schema}"."{table}"')
        columns = [str(item[0]) for item in read_cursor.description]
        rows = [tuple(_cell(value) for value in row) for row in read_cursor]
    if not rows:
        return 0
    column_list = ", ".join(f'"{name}"' for name in columns)
    placeholders = ", ".join(f":{index}" for index in range(1, len(columns) + 1))
    statement = f'insert into "{schema}"."{table}" ({column_list}) values ({placeholders})'
    with target.connection().cursor() as write_cursor:
        write_cursor.executemany(statement, rows)
    target.connection().commit()
    return len(rows)


def _count(database: _Database, schema: str, table: str) -> int:
    rows = database.query(f'select count(*) from "{schema}"."{table}"')
    return int(rows[0][0])


def copy_schema(
    source_name: str,
    target_name: str,
    schema_name: str,
    *,
    confirmed: bool,
    tablespace_remap: dict[str, str] | None,
    connect: Callable[[str], Any],
    resume: bool = False,
) -> dict[str, Any]:
    """Create one schema from metadata and copy its rows. Stop if it exists."""
    if source_name == target_name:
        raise ValueError("source and target connections must be different")
    schema = normalize_schema(schema_name)
    remap = normalize_remap(tablespace_remap)
    source = _Database(source_name, connect)
    target = _Database(target_name, connect)
    secret = ""
    try:
        if not _exists(source, schema):
            raise ValueError(f"{source_name} has no schema {schema}")
        already = _exists(target, schema)
        if already and not resume:
            return {
                "status": "stopped",
                "reason": "destination schema already exists",
                "source": source_name,
                "target": target_name,
                "schema": schema,
            }
        if not confirmed:
            return {
                "status": "not_confirmed",
                "source": source_name,
                "target": target_name,
                "schema": schema,
                "tablespace_remap": remap,
            }
        secret = _hash(source, schema) if not already else ""
        if not already:
            target_tablespace = next(iter(remap.values()), "")
            if target_tablespace and target_tablespace not in {
                str(row[0]) for row in target.query("select tablespace_name from dba_tablespaces")
            }:
                raise ValueError(f"Target tablespace {target_tablespace} does not exist")
            default_tablespace = target_tablespace or "USERS"
            target.call(
                f'create user "{schema}" identified by values \'{secret}\' '
                f'default tablespace "{default_tablespace}" temporary tablespace "TEMP" '
                f'quota unlimited on "{default_tablespace}"'
            )
            for role in ("CONNECT", "RESOURCE"):
                if _grantee_exists(target, role):
                    target.call(f'grant {role} to "{schema}"')
        _configure_metadata(source)
        objects = _objects(source, schema)
        constraint_indexes = _constraint_indexes(source, schema)
        temporary = _temporary_tables(source, schema)
        created: list[str] = []
        errors: list[dict[str, str]] = []
        failed_tables: set[str] = set()

        def should_skip(object_type: str, object_name: str) -> bool:
            rows = target.query(
                "select status from dba_objects "
                "where owner = :schema and object_type = :object_type and object_name = :object_name",
                {"schema": schema, "object_type": object_type, "object_name": object_name},
            )
            if not rows:
                return False
            replaceable = object_type in {"FUNCTION", "PACKAGE", "PACKAGE BODY", "VIEW", "TRIGGER"}
            return not replaceable or str(rows[0][0]) == "VALID"

        for object_type in _CREATE_ORDER:
            if object_type == "TRIGGER":
                continue
            for found_type, object_name in objects:
                if found_type != object_type:
                    continue
                if object_type == "INDEX" and object_name in constraint_indexes:
                    continue
                if should_skip(object_type, object_name):
                    continue
                table_created = object_type != "TABLE"
                mode = "table" if object_type in {"TABLE", "INDEX"} else "view"
                try:
                    if object_type in {"FUNCTION", "PACKAGE", "PACKAGE BODY"}:
                        statements = [_plsql_ddl(source, object_type, object_name, schema)]
                    else:
                        statements = sql_statements(
                            remap_ddl(_ddl(source, object_type, object_name, schema), remap),
                            "table" if mode == "table" else "none",
                        )
                    if not statements:
                        raise ValueError("empty DDL")
                    for statement in statements:
                        target.call(statement)
                        if statement.upper().startswith("CREATE TABLE"):
                            table_created = True
                    created.append(f"{object_type} {object_name}")
                except Exception as exc:
                    if object_type == "TABLE" and not table_created:
                        failed_tables.add(object_name)
                    errors.append({
                        "object": f"{object_type} {object_name}",
                        "error": _safe(str(exc), secret),
                    })
        row_counts: dict[str, int] = {}
        for _object_type, object_name in objects:
            if _object_type != "TABLE" or object_name in failed_tables or object_name in temporary:
                continue
            try:
                source_count = _count(source, schema, object_name)
                target_count = _count(target, schema, object_name)
                if target_count == source_count:
                    row_counts[object_name] = target_count
                    continue
                if target_count != 0:
                    errors.append({
                        "object": f"TABLE {object_name}",
                        "error": f"row count source {source_count} target {target_count}",
                    })
                    row_counts[object_name] = target_count
                    continue
                _copy_rows(source, target, schema, object_name)
                target_count = _count(target, schema, object_name)
                row_counts[object_name] = target_count
                if target_count != source_count:
                    errors.append({
                        "object": f"TABLE {object_name}",
                        "error": f"row count source {source_count} target {target_count}",
                    })
            except Exception as exc:
                errors.append({"object": f"TABLE {object_name}", "error": _safe(str(exc), secret)})
        for constraint_name in _ref_constraints(source, schema):
            if target.query(
                "select constraint_name from dba_constraints "
                "where owner = :schema and constraint_name = :name",
                {"schema": schema, "name": constraint_name},
            ):
                continue
            try:
                rows = source.query(
                    "select dbms_metadata.get_ddl('REF_CONSTRAINT', :name, :schema) from dual",
                    {"name": constraint_name, "schema": schema},
                )
                statement = remap_ddl(_text(rows[0][0] if rows else ""), remap)
                for piece in sql_statements(statement, "table"):
                    target.call(piece)
                created.append(f"REF_CONSTRAINT {constraint_name}")
            except Exception as exc:
                errors.append({
                    "object": f"REF_CONSTRAINT {constraint_name}",
                    "error": _safe(str(exc), secret),
                })
        for found_type, object_name in objects:
            if found_type != "TRIGGER" or should_skip("TRIGGER", object_name):
                continue
            try:
                statements = [qualify_trigger(_plsql_ddl(source, found_type, object_name, schema), schema)]
                if not statements:
                    raise ValueError("empty DDL")
                for statement in statements:
                    target.call(statement)
                created.append(f"{found_type} {object_name}")
            except Exception as exc:
                errors.append({
                    "object": f"{found_type} {object_name}",
                    "error": _safe(str(exc), secret),
                })
        granted = 0
        missing_grantees: set[str] = set()
        for grantee, privilege, table_name in _grants(source, schema):
            if not _IDENTIFIER.fullmatch(grantee) or not _IDENTIFIER.fullmatch(table_name):
                continue
            if not _PRIVILEGE.fullmatch(privilege.strip().upper()):
                continue
            if grantee in missing_grantees:
                continue
            if not _grantee_exists(target, grantee):
                missing_grantees.add(grantee)
                errors.append({"object": f"GRANT {grantee}", "error": "grantee does not exist"})
                continue
            try:
                target.call(
                    f'grant {privilege.strip().upper()} on "{schema}"."{table_name}" to "{grantee}"'
                )
                granted += 1
            except Exception as exc:
                errors.append({
                    "object": f"GRANT {grantee} {table_name}",
                    "error": _safe(str(exc), secret),
                })
        return {
            "status": "copied_with_errors" if errors else "copied",
            "source": source_name,
            "target": target_name,
            "schema": schema,
            "tablespace_remap": remap,
            "objects_created": len(created),
            "grants_applied": granted,
            "row_counts": row_counts,
            "errors": errors[:80],
        }
    finally:
        source.close()
        target.close()
