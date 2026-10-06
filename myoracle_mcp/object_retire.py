"""Retire unused Oracle objects on a saved target.

The module holds the logic; the MCP tool in ``server.py`` validates the
user-facing arguments and delegates here. It never opens a saved connection
itself -- the caller supplies the ``connect`` callable.
"""

from __future__ import annotations

import re
from typing import Any, Callable

_IDENTIFIER = re.compile(r"[A-Z][A-Z0-9_$#]{0,29}")


def drop_saved_materialized_view(
    connection_name: str,
    owner: str,
    name: str,
    confirmed: bool,
    connect: Callable[[str], Any],
) -> dict[str, Any]:
    """Drop one materialized view after verifying it exists and is unused."""
    if not confirmed:
        raise ValueError("confirmed must be true after explicit approval for this write operation.")
    if not str(connection_name or "").strip():
        raise ValueError("connection_name must not be empty.")
    safe_owner = str(owner or "").strip().upper()
    safe_name = str(name or "").strip().upper()
    if not _IDENTIFIER.fullmatch(safe_owner) or not _IDENTIFIER.fullmatch(safe_name):
        raise ValueError("owner and name must be simple Oracle identifiers.")
    connection = connect(connection_name)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select m.last_refresh_date, m.staleness, m.compile_state "
                "from dba_mviews m where m.owner = :owner and m.mview_name = :name",
                {"owner": safe_owner, "name": safe_name},
            )
            mview_row = cursor.fetchone()
            if mview_row is None:
                raise ValueError(f"Materialized view {safe_owner}.{safe_name} was not found.")
            last_refresh, staleness, compile_state = mview_row
            cursor.execute(
                "select owner, name, type from dba_dependencies "
                "where referenced_owner = :owner and referenced_name = :name "
                "and referenced_type = 'MATERIALIZED VIEW' "
                "order by owner, type, name",
                {"owner": safe_owner, "name": safe_name},
            )
            dependents = [
                {"owner": str(dep_owner), "name": str(dep_name), "type": str(dep_type)}
                for dep_owner, dep_name, dep_type in cursor
            ]
            if dependents:
                raise ValueError(
                    f"Refusing to drop {safe_owner}.{safe_name}: "
                    f"{len(dependents)} dependent object(s) exist."
                )
            try:
                cursor.execute(f'DROP MATERIALIZED VIEW "{safe_owner}"."{safe_name}"')
            except Exception as exc:
                raise RuntimeError(str(exc).splitlines()[0][:300]) from None
        connection.commit()
        with connection.cursor() as cursor:
            cursor.execute(
                "select count(*) from dba_mviews where owner = :owner and mview_name = :name",
                {"owner": safe_owner, "name": safe_name},
            )
            remaining_row = cursor.fetchone()
            remaining = int(remaining_row[0]) if remaining_row else -1
        if remaining != 0:
            raise RuntimeError(f"Drop issued but {safe_owner}.{safe_name} is still present.")
        return {
            "connection": connection_name,
            "owner": safe_owner,
            "name": safe_name,
            "last_refresh_date": str(last_refresh) if last_refresh else None,
            "staleness": str(staleness) if staleness else None,
            "compile_state": str(compile_state) if compile_state else None,
            "dependents_before_drop": dependents,
            "status": "dropped",
        }
    finally:
        connection.close()
