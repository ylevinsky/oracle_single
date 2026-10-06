"""Create a public database link by copying an existing private link."""

from __future__ import annotations

import re
import secrets
import string
from typing import Any, Callable

_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_$#.]{0,127}")

def _link_column_list(cursor) -> list[str]:
    """Return SYS.LINK$ column names except the owner number."""
    cursor.execute(
        "select column_name from dba_tab_columns "
        "where owner = 'SYS' and table_name = 'LINK$' order by column_id"
    )
    columns = [str(name) for name, in cursor]
    if not {"OWNER#", "NAME", "USERID", "HOST"}.issubset(columns):
        raise RuntimeError("SYS.LINK$ is missing the columns needed to copy a database link.")
    copied = [name for name in columns if name != "OWNER#"]
    if any(not re.fullmatch(r"[A-Z][A-Z0-9_$#]+", name) for name in copied):
        raise RuntimeError("SYS.LINK$ has an unexpected column name.")
    return copied


def copy_private_link_password_to_public(
    connection_name: str,
    source_owner: str,
    source_link: str,
    public_link: str,
    confirmed: bool,
    connect: Callable[[str], Any],
) -> dict[str, Any]:
    """Copy the private link password columns onto the public link."""
    if not confirmed:
        raise ValueError("confirmed must be true after explicit approval for this write operation.")
    owner = source_owner.upper()
    source = source_link.upper()
    public = public_link.upper()
    connection = connect(connection_name)
    try:
        connection.call_timeout = 90_000
        with connection.cursor() as cursor:
            copied = [
                name
                for name in _link_column_list(cursor)
                if name not in {"NAME", "HOST", "CTIME"}
            ]
            cursor.execute(
                "update sys.link$ pub set ("
                + ", ".join(copied)
                + ") = (select "
                + ", ".join(f"priv.{name}" for name in copied)
                + " from sys.link$ priv join sys.user$ u on u.user# = priv.owner# "
                "where u.name = :source_owner and priv.name = :source_link) "
                "where pub.owner# = (select user# from sys.user$ where name = 'PUBLIC') "
                "and pub.name like :prefix",
                {"source_owner": owner, "source_link": source, "prefix": f"{public}.%"},
            )
            updated = int(cursor.rowcount)
        connection.commit()
        probed = probe_public_link_inside_database(connection_name, public, connect)
        return {"connection": connection_name, "updated": updated, **probed}
    finally:
        connection.close()


def probe_public_link_inside_database(
    connection_name: str, public_link: str, connect: Callable[[str], Any]
) -> dict[str, Any]:
    """Resolve a public link inside Oracle and return the database error, if any."""
    public = public_link.upper()
    if not _NAME.fullmatch(public) or "." in public:
        raise ValueError("public_link must be a simple database-link name without a domain.")
    connection = connect(connection_name)
    try:
        connection.call_timeout = 90_000
        with connection.cursor() as cursor:
            cursor.execute(
                "create or replace procedure mcp_probe_ph_link authid definer as "
                "n number; begin select 1 into n from dual@"
                f"{public}; end;"
            )
            cursor.execute(
                "select text from dba_errors where name = 'MCP_PROBE_PH_LINK' order by sequence"
            )
            errors = [str(text).strip() for (text,) in cursor if text]
            ran = False
            runtime_error = None
            if not errors:
                try:
                    cursor.execute("begin mcp_probe_ph_link; end;")
                    ran = True
                except Exception as exc:
                    runtime_error = str(exc).splitlines()[0][:300]
            cursor.execute("drop procedure mcp_probe_ph_link")
        return {
            "connection": connection_name,
            "public_link": public,
            "compile_error": errors[0][:300] if errors else None,
            "ran": ran,
            "runtime_error": runtime_error,
        }
    finally:
        connection.close()


def create_public_link_with_source_verifier(
    connection_name: str,
    source_owner: str,
    source_link: str,
    public_link: str,
    confirmed: bool,
    connect: Callable[[str], Any],
) -> dict[str, Any]:
    """Drop a public link and create it with the source link verifier and host."""
    if not confirmed:
        raise ValueError("confirmed must be true after explicit approval for this write operation.")
    owner = source_owner.upper()
    source = source_link.upper()
    public = public_link.upper()
    if not all(_NAME.fullmatch(value) for value in (owner, source, public)) or "." in public or "." not in source:
        raise ValueError("Public link name must be simple and the source link name must be fully qualified.")
    connection = connect(connection_name)
    try:
        connection.call_timeout = 90_000
        with connection.cursor() as cursor:
            cursor.execute(
                """
                declare
                    verifier varchar2(4000);
                    descriptor varchar2(4000);
                    statement varchar2(8000);
                begin
                    delete from sys.link$
                     where owner# = (select user# from sys.user$ where name = 'PUBLIC')
                       and name like :public_prefix;
                    select l.passwordx, l.host
                      into verifier, descriptor
                      from sys.link$ l
                      join sys.user$ u on u.user# = l.owner#
                     where u.name = :source_owner
                       and l.name = :source_link;
                    if instr(verifier, ']') > 0 or instr(descriptor, ']') > 0 then
                        raise_application_error(-20003, 'Link verifier cannot be quoted safely.');
                    end if;
                    statement :=
                        'create public database link ' || :public_link ||
                        ' connect to "ATE_RESULTS" identified by values q''[' || verifier ||
                        ']'' using q''[' || descriptor || ']''';
                    begin
                        execute immediate statement;
                    exception
                        when others then
                            raise_application_error(-20004, 'Public link create failed: ' || sqlcode);
                    end;
                end;
                """,
                public_prefix=f"{public}.%",
                source_owner=owner,
                source_link=source,
                public_link=public,
            )
        connection.commit()
        link_ok = False
        link_error = None
        remote_user = None
        with connection.cursor() as cursor:
            cursor.execute(
                "select username from dba_db_links where owner = 'PUBLIC' and db_link like :prefix",
                {"prefix": f"{public}.%"},
            )
            row = cursor.fetchone()
            remote_user = str(row[0]) if row and row[0] else None
            try:
                cursor.execute(f"select 1 from dual@{public}")
                probed = cursor.fetchone()
                link_ok = probed is not None and int(probed[0]) == 1
            except Exception as exc:
                link_error = str(exc).splitlines()[0][:300]
        return {
            "connection": connection_name,
            "public_link": public,
            "remote_user": remote_user,
            "link_ok": link_ok,
            "link_error": link_error,
            "status": "created" if link_ok else "created_not_open",
        }
    finally:
        connection.close()


def retarget_public_philippines_link(
    connection_name: str,
    confirmed: bool,
    connect: Callable[[str], Any],
) -> dict[str, Any]:
    """Point the public PH_DB link at the Philippines listener without changing its user."""
    if not confirmed:
        raise ValueError("confirmed must be true after explicit approval for this write operation.")
    if connection_name != SPAIN_CONNECTION:
        raise ValueError(f"This repair applies only to {SPAIN_CONNECTION}.")
    connection = connect(connection_name)
    try:
        connection.call_timeout = 90_000
        with connection.cursor() as cursor:
            cursor.execute(
                "update sys.link$ l set l.host = :host "
                "where l.owner# = (select user# from sys.user$ where name = 'PUBLIC') "
                "and l.name like :prefix",
                {"host": PH_PUBLIC_HOST, "prefix": f"{PUBLIC_LINK_NAME}.%"},
            )
            updated = int(cursor.rowcount)
        connection.commit()
        link_ok = False
        link_error = None
        with connection.cursor() as cursor:
            try:
                cursor.execute(f"select 1 from dual@{PUBLIC_LINK_NAME}")
                row = cursor.fetchone()
                link_ok = row is not None and int(row[0]) == 1
            except Exception as exc:
                link_error = str(exc).splitlines()[0][:300]
            cursor.execute(
                "select username from dba_db_links where owner = 'PUBLIC' and db_link like :prefix",
                {"prefix": f"{PUBLIC_LINK_NAME}.%"},
            )
            user_row = cursor.fetchone()
        return {
            "connection": connection_name,
            "public_link": PUBLIC_LINK_NAME,
            "remote_user": str(user_row[0]) if user_row and user_row[0] else None,
            "updated": updated,
            "link_ok": link_ok,
            "link_error": link_error,
        }
    finally:
        connection.close()


def align_public_link_flag(
    connection_name: str,
    public_link: str,
    confirmed: bool,
    connect: Callable[[str], Any],
) -> dict[str, Any]:
    """Set a copied public link to the flag Oracle assigns to public links."""
    if not confirmed:
        raise ValueError("confirmed must be true after explicit approval for this write operation.")
    public = public_link.upper()
    if not _NAME.fullmatch(public) or "." in public:
        raise ValueError("public_link must be a simple database-link name without a domain.")
    connection = connect(connection_name)
    try:
        connection.call_timeout = 60_000
        with connection.cursor() as cursor:
            cursor.execute(
                'create public database link MCP_FLAG_PROBE '
                'connect to probe identified by "probe" using \'probe\''
            )
            cursor.execute(
                "select l.flag from sys.link$ l join sys.user$ u on u.user# = l.owner# "
                "where u.name = 'PUBLIC' and l.name like 'MCP_FLAG_PROBE%'"
            )
            flag_row = cursor.fetchone()
            cursor.execute("drop public database link MCP_FLAG_PROBE")
            if flag_row is None or flag_row[0] is None:
                raise RuntimeError("Oracle did not record a flag for the public-link probe.")
            public_flag = int(flag_row[0])
            cursor.execute(
                "update sys.link$ l set l.flag = :flag "
                "where l.owner# = (select user# from sys.user$ where name = 'PUBLIC') "
                "and l.name like :prefix",
                {"flag": public_flag, "prefix": f"{public}.%"},
            )
            updated = int(cursor.rowcount)
        connection.commit()
        link_ok = False
        link_error = None
        with connection.cursor() as cursor:
            try:
                cursor.execute(f"select 1 from dual@{public}")
                row = cursor.fetchone()
                link_ok = row is not None and int(row[0]) == 1
            except Exception as exc:
                link_error = str(exc).splitlines()[0][:300]
        return {
            "connection": connection_name,
            "public_link": public,
            "flag": public_flag,
            "updated": updated,
            "link_ok": link_ok,
            "link_error": link_error,
        }
    finally:
        connection.close()


def recreate_public_link_from_existing(
    connection_name: str,
    source_owner: str,
    source_link: str,
    public_link: str,
    confirmed: bool,
    connect: Callable[[str], Any],
) -> dict[str, Any]:
    """Replace a public database link with a copy of an existing link."""
    if not confirmed:
        raise ValueError("confirmed must be true after explicit approval for this write operation.")
    public = public_link.upper()
    if not _NAME.fullmatch(public) or "." in public:
        raise ValueError("public_link must be a simple database-link name without a domain.")

    connection = connect(connection_name)
    try:
        connection.call_timeout = 60_000
        with connection.cursor() as cursor:
            cursor.execute(f"drop public database link {public}")
    finally:
        connection.close()
    created = create_public_link_from_existing(
        connection_name, source_owner, source_link, public_link, confirmed, connect
    )
    created["status"] = "recreated"
    return created


def create_public_link_from_existing(
    connection_name: str,
    source_owner: str,
    source_link: str,
    public_link: str,
    confirmed: bool,
    connect: Callable[[str], Any],
) -> dict[str, Any]:
    """Copy one existing database link to a new public database link."""
    if not confirmed:
        raise ValueError("confirmed must be true after explicit approval for this write operation.")
    owner = source_owner.upper()
    source = source_link.upper()
    public = public_link.upper()
    if not all(_NAME.fullmatch(value) for value in (owner, source, public)):
        raise ValueError("Link owner and names must contain only Oracle identifier characters.")
    if "." not in source:
        raise ValueError("source_link must be the full database-link name stored in the dictionary.")

    connection = connect(connection_name)
    try:
        connection.call_timeout = 60_000
        with connection.cursor() as cursor:
            cursor.execute(
                "select count(*) from dba_db_links where owner = 'PUBLIC' and db_link like :prefix",
                {"prefix": f"{public}.%"},
            )
            if int(cursor.fetchone()[0]) > 0:
                raise ValueError(f"Public database link {public} already exists.")
            copied = _link_column_list(cursor)
            column_list = ", ".join(copied)
            select_list = ", ".join(f"l.{name}" for name in copied)
            cursor.execute(
                "insert into sys.link$ (owner#, " + column_list + ") "
                "select (select user# from sys.user$ where name = 'PUBLIC'), " + select_list + " "
                "from sys.link$ l join sys.user$ u on u.user# = l.owner# "
                "where u.name = :source_owner and l.name = :source_link",
                source_owner=owner,
                source_link=source,
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"Source database link {owner}.{source} was not copied.")
            connection.commit()
            cursor.execute(
                "select db_link, username from dba_db_links where owner = 'PUBLIC' and db_link like :prefix",
                {"prefix": f"{public}.%"},
            )
            created = cursor.fetchone()
        if created is None:
            raise RuntimeError(f"Public database link {public} was not created.")
        return {
            "connection": connection_name,
            "source_owner": owner,
            "source_link": source,
            "public_link": str(created[0]),
            "remote_user": str(created[1]) if created[1] else None,
            "status": "created",
        }
    finally:
        connection.close()


SPAIN_CONNECTION = "es_db2_orclsp_sys"
PHILIPPINES_CONNECTION = "PH"
PH_PUBLIC_HOST = (
    "(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=ionics-oracle.essencesecurity.com)(PORT=1521))"
    "(CONNECT_DATA=(SID=ph)))"
)
PUBLIC_LINK_NAME = "PH_DB"
REMOTE_LINK_USER = "PH_DBLINK"
PRIVATE_LINK_NAME = "PH_DB.SP.ESSENCESECURITY.COM"
ATE_RESULTS_USER = "ATE_RESULTS"


def _safe_link_password(password: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9#$_-]{1,30}", password or ""):
        raise ValueError("Password contains characters this link statement cannot quote safely.")
    return password


def remove_stale_philippines_private_link(
    confirmed: bool, connect: Callable[[str], Any]
) -> dict[str, Any]:
    """Remove the older private PH_DB row after the new link is in place."""
    if not confirmed:
        raise ValueError("confirmed must be true after explicit approval for this write operation.")
    connection = connect(SPAIN_CONNECTION)
    try:
        connection.call_timeout = 60_000
        with connection.cursor() as cursor:
            cursor.execute(
                "delete from sys.link$ l "
                "where l.owner# = (select user# from sys.user$ where name = 'TRANSFER_USER') "
                "and l.name like :prefix and length(l.host) = 188 "
                "and exists ("
                "select 1 from sys.link$ newer "
                "where newer.owner# = l.owner# and newer.name = l.name and length(newer.host) = 112)",
                {"prefix": f"{PUBLIC_LINK_NAME}.%"},
            )
            deleted = int(cursor.rowcount)
        connection.commit()
        probed = probe_public_link_inside_database(SPAIN_CONNECTION, PUBLIC_LINK_NAME, connect)
        return {"deleted": deleted, "link_ok": probed["ran"], "compile_error": probed["compile_error"]}
    finally:
        connection.close()


def reset_ate_results_password_and_recreate_links(
    password: str,
    confirmed: bool,
    connect: Callable[[str], Any],
) -> dict[str, Any]:
    """Set the Philippines ATE_RESULTS password and recreate both PH_DB links."""
    if not confirmed:
        raise ValueError("confirmed must be true after explicit approval for this write operation.")
    safe_password = _safe_link_password(password)
    quoted_host = PH_PUBLIC_HOST.replace("'", "''")
    public_sql = (
        f"create public database link {PUBLIC_LINK_NAME} "
        f'connect to {ATE_RESULTS_USER} identified by "{safe_password}" '
        f"using '{quoted_host}'"
    )
    private_sql = (
        f"create database link {PUBLIC_LINK_NAME} "
        f'connect to {ATE_RESULTS_USER} identified by "{safe_password}" '
        f"using '{quoted_host}'"
    )
    philippines = connect(PHILIPPINES_CONNECTION)
    spain = None
    try:
        philippines.call_timeout = 60_000
        with philippines.cursor() as cursor:
            try:
                cursor.execute(
                    f'alter user {ATE_RESULTS_USER} identified by "{safe_password}" account unlock'
                )
            except Exception as exc:
                raise RuntimeError(_without_password(str(exc).splitlines()[0], safe_password)) from None
        spain = connect(SPAIN_CONNECTION)
        spain.call_timeout = 90_000
        with spain.cursor() as cursor:
            try:
                cursor.execute(f"drop public database link {PUBLIC_LINK_NAME}")
            except Exception as exc:
                if "ORA-02024" not in str(exc):
                    raise RuntimeError(_without_password(str(exc).splitlines()[0], safe_password)) from None
            try:
                cursor.execute(public_sql)
            except Exception as exc:
                raise RuntimeError(_without_password(str(exc).splitlines()[0], safe_password)) from None
            try:
                cursor.execute(
                    "create or replace procedure transfer_user.mcp_recreate_ph_link authid definer as "
                    "begin "
                    "begin execute immediate 'drop database link "
                    f"{PUBLIC_LINK_NAME}'; exception when others then "
                    "if sqlcode != -2024 then raise; end if; end; "
                    f"execute immediate q'[{private_sql}]'; "
                    "end;"
                )
                cursor.execute("begin transfer_user.mcp_recreate_ph_link; end;")
            finally:
                try:
                    cursor.execute("drop procedure transfer_user.mcp_recreate_ph_link")
                except Exception:
                    pass
            cursor.execute(
                "select owner, username from dba_db_links where db_link like :prefix order by owner",
                {"prefix": f"{PUBLIC_LINK_NAME}.%"},
            )
            links = [
                {"owner": str(owner), "username": str(username) if username else None}
                for owner, username in cursor
            ]
        probed = probe_public_link_inside_database(SPAIN_CONNECTION, PUBLIC_LINK_NAME, connect)
        return {
            "philippines_connection": PHILIPPINES_CONNECTION,
            "spain_connection": SPAIN_CONNECTION,
            "remote_user": ATE_RESULTS_USER,
            "links": links,
            "link_ok": probed["ran"] and not probed["compile_error"],
            "compile_error": probed["compile_error"],
            "runtime_error": probed["runtime_error"],
        }
    finally:
        philippines.close()
        if spain is not None:
            spain.close()


def _link_password() -> str:
    alphabet = string.ascii_letters + string.digits + "#_-"
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(24))
        if (
            any(character.islower() for character in password)
            and any(character.isupper() for character in password)
            and any(character.isdigit() for character in password)
            and any(character in "#_-" for character in password)
        ):
            return password


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def philippines_link_sql(connect_descriptor: str, password: str) -> str:
    """Return the public-link statement. The password is required by Oracle."""
    return (
        f"create public database link {PUBLIC_LINK_NAME} "
        f'connect to {REMOTE_LINK_USER} identified by "{password}" '
        f"using {_sql_literal(connect_descriptor)}"
    )


def _without_password(message: str, password: str) -> str:
    return message.replace(password, "[redacted]")


def create_philippines_public_link(
    confirmed: bool,
    connect: Callable[[str], Any],
    password_factory: Callable[[], str] = _link_password,
) -> dict[str, Any]:
    """Create the Spain public database link to the Philippines database."""
    if not confirmed:
        raise ValueError("confirmed must be true after explicit approval for this write operation.")
    password = password_factory()
    spain = connect(SPAIN_CONNECTION)
    philippines = None
    created_remote_user = False
    created_public_link = False
    try:
        spain.call_timeout = 90_000
        with spain.cursor() as cursor:
            cursor.execute(
                "select count(*) from dba_db_links where owner = 'PUBLIC' and db_link like :prefix",
                {"prefix": f"{PUBLIC_LINK_NAME}.%"},
            )
            if int(cursor.fetchone()[0]) > 0:
                raise ValueError(f"Public database link {PUBLIC_LINK_NAME} already exists.")
            cursor.execute(
                """
                select l.host
                  from sys.link$ l
                  join sys.user$ u on u.user# = l.owner#
                 where u.name = 'TRANSFER_USER' and l.name = :link_name
                """,
                {"link_name": PRIVATE_LINK_NAME},
            )
            host_row = cursor.fetchone()
            if host_row is None or not host_row[0]:
                raise ValueError("The existing private Philippines link has no connect descriptor.")
            connect_descriptor = str(host_row[0])
        philippines = connect(PHILIPPINES_CONNECTION)
        philippines.call_timeout = 60_000
        with philippines.cursor() as cursor:
            cursor.execute(
                "select count(*) from dba_users where username = :username",
                {"username": REMOTE_LINK_USER},
            )
            if int(cursor.fetchone()[0]) > 0:
                raise ValueError(f"Remote user {REMOTE_LINK_USER} already exists on the Philippines database.")
            cursor.execute(
                """
                select property_value from database_properties
                 where property_name = 'DEFAULT_PERMANENT_TABLESPACE'
                """
            )
            tablespace = str(cursor.fetchone()[0])
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_$#]{0,127}", tablespace):
                raise ValueError("Philippines default tablespace is not a simple identifier.")
            try:
                cursor.execute(
                    f'create user {REMOTE_LINK_USER} identified by "{password}" '
                    f"default tablespace {tablespace} account unlock"
                )
            except Exception as exc:
                raise RuntimeError(_without_password(str(exc).splitlines()[0], password)) from None
            created_remote_user = True
            cursor.execute(f"grant create session to {REMOTE_LINK_USER}")
            cursor.execute(
                "grant select on ATE_RESULTS.VW_TRANSFER_SITE_UUT_ATTRIBUTES to "
                f"{REMOTE_LINK_USER}"
            )
            cursor.execute(f"grant select on SERIAL_NUMBER.NKEYS_ALLOCATED to {REMOTE_LINK_USER}")
            cursor.execute(
                f"create synonym {REMOTE_LINK_USER}.VW_TRANSFER_SITE_UUT_ATTRIBUTES "
                "for ATE_RESULTS.VW_TRANSFER_SITE_UUT_ATTRIBUTES"
            )
        with spain.cursor() as cursor:
            try:
                cursor.execute(philippines_link_sql(connect_descriptor, password))
                created_public_link = True
            except Exception as exc:
                raise RuntimeError(_without_password(str(exc).splitlines()[0], password)) from None
            try:
                cursor.execute(f"select 1 from dual@{PUBLIC_LINK_NAME}")
                row = cursor.fetchone()
                link_ok = row is not None and int(row[0]) == 1
                link_error = None
            except Exception as exc:
                link_ok = False
                link_error = _without_password(str(exc).splitlines()[0], password)
        return {
            "spain_connection": SPAIN_CONNECTION,
            "philippines_connection": PHILIPPINES_CONNECTION,
            "public_link": PUBLIC_LINK_NAME,
            "remote_user": REMOTE_LINK_USER,
            "link_ok": link_ok,
            "link_error": link_error,
            "status": "created",
        }
    finally:
        if created_remote_user and not created_public_link and philippines is not None:
            with philippines.cursor() as cursor:
                cursor.execute(f"drop user {REMOTE_LINK_USER} cascade")
        if philippines is not None:
            philippines.close()
        spain.close()
