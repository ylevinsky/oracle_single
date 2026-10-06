"""Read-only listing of databases on a saved PostgreSQL connection."""

from __future__ import annotations

from typing import Any

import psycopg2


_LIST_DATABASES_SQL = """
SELECT datname,
       pg_catalog.pg_get_userbyid(datdba),
       pg_catalog.pg_encoding_to_char(encoding),
       pg_catalog.pg_size_pretty(pg_catalog.pg_database_size(datname)),
       datallowconn
FROM pg_catalog.pg_database
ORDER BY datname
"""


def list_databases(connection: dict[str, Any]) -> dict[str, Any]:
    """Return every database visible to one already-validated PostgreSQL login."""
    with psycopg2.connect(
        host=connection["host"],
        port=int(connection["port"]),
        dbname=connection["database"],
        user=connection["username"],
        password=connection["password"],
        sslmode=connection.get("sslmode") or "disable",
        connect_timeout=10,
    ) as database:
        with database.cursor() as cursor:
            cursor.execute(_LIST_DATABASES_SQL)
            rows = cursor.fetchall()
    return {
        "connection_name": connection["connection_name"],
        "host": connection["host"],
        "port": int(connection["port"]),
        "databases": [
            {
                "name": row[0],
                "owner": row[1],
                "encoding": row[2],
                "size": row[3],
                "allow_connections": bool(row[4]),
            }
            for row in rows
        ],
    }
