"""Create or reset a read-only monitoring user on a saved Oracle target.

The module holds the logic; the MCP tool in ``server.py`` validates the
user-facing arguments and delegates here. It never opens a saved connection
itself -- the caller supplies the ``connect`` callable.
"""

from __future__ import annotations

import re
from typing import Any, Callable

_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_$#]{0,127}")


def _without_password(message: str, password: str) -> str:
    if password and password in message:
        return message.replace(password, "[redacted]")
    return message


def _quote_password(password: str) -> str:
    # Double-quoted password with embedded quotes escaped as "".
    return '"' + password.replace('"', '""') + '"'


def create_readonly_user(
    connection_name: str,
    username: str,
    password: str,
    confirmed: bool,
    connect: Callable[[str], Any],
    with_dictionary_access: bool = False,
) -> dict[str, Any]:
    """Create (or reset) a read-only user that can select any table."""
    if not confirmed:
        raise ValueError("confirmed must be true after explicit approval for this write operation.")
    if not str(connection_name or "").strip():
        raise ValueError("connection_name must not be empty.")
    safe_user = str(username or "").strip().upper()
    if not _IDENTIFIER.fullmatch(safe_user):
        raise ValueError("username must be a simple Oracle identifier.")
    safe_password = str(password or "")
    if not safe_password or len(safe_password) > 128:
        raise ValueError("password must be 1-128 characters.")
    if any(character in safe_password for character in ("\n", "\r", "\x00")):
        raise ValueError("password contains characters this statement cannot quote safely.")

    quoted_password = _quote_password(safe_password)
    connection = connect(connection_name)
    try:
        connection.call_timeout = 60_000
        with connection.cursor() as cursor:
            cursor.execute(
                "select count(*) from dba_users where username = :username",
                {"username": safe_user},
            )
            exists_row = cursor.fetchone()
            existed = int(exists_row[0]) > 0 if exists_row else False
            if existed:
                try:
                    cursor.execute(
                        f"alter user {safe_user} identified by {quoted_password} account unlock"
                    )
                except Exception as exc:
                    raise RuntimeError(
                        _without_password(str(exc).splitlines()[0][:300], safe_password)
                    ) from None
            else:
                tablespace = None
                try:
                    cursor.execute(
                        "select property_value from database_properties "
                        "where property_name = 'DEFAULT_PERMANENT_TABLESPACE'"
                    )
                    tablespace_row = cursor.fetchone()
                    if tablespace_row and tablespace_row[0]:
                        candidate = str(tablespace_row[0])
                        if _IDENTIFIER.fullmatch(candidate):
                            tablespace = candidate
                except Exception:
                    tablespace = None
                try:
                    if tablespace:
                        cursor.execute(
                            f"create user {safe_user} identified by {quoted_password} "
                            f"default tablespace {tablespace} account unlock"
                        )
                    else:
                        cursor.execute(
                            f"create user {safe_user} identified by {quoted_password} account unlock"
                        )
                except Exception as exc:
                    raise RuntimeError(
                        _without_password(str(exc).splitlines()[0][:300], safe_password)
                    ) from None
            grants = ["CREATE SESSION", "SELECT ANY TABLE"]
            if with_dictionary_access:
                grants.append("SELECT ANY DICTIONARY")
            for privilege in grants:
                try:
                    cursor.execute(f"grant {privilege} to {safe_user}")
                except Exception as exc:
                    raise RuntimeError(
                        _without_password(str(exc).splitlines()[0][:300], safe_password)
                    ) from None
        connection.commit()
        with connection.cursor() as cursor:
            cursor.execute(
                "select username, account_status, default_tablespace from dba_users "
                "where username = :username",
                {"username": safe_user},
            )
            user_row = cursor.fetchone()
            cursor.execute(
                "select privilege from dba_sys_privs where grantee = :grantee order by privilege",
                {"grantee": safe_user},
            )
            system_privileges = [str(row[0]) for row in cursor if row and row[0]]
        if user_row is None:
            raise RuntimeError(f"User {safe_user} was not found after creation.")
        return {
            "connection": connection_name,
            "username": str(user_row[0]),
            "account_status": str(user_row[1]),
            "default_tablespace": str(user_row[2]) if len(user_row) > 2 else None,
            "existed_before": existed,
            "granted": grants,
            "system_privileges": system_privileges,
            "dictionary_access": with_dictionary_access,
            "status": "reset" if existed else "created",
        }
    finally:
        connection.close()
