"""Query V$ACTIVE_SESSION_HISTORY for the last 15 minutes."""

from myoracle_mcp.server import _connect_saved_oracle

CONNECTION = "es_db2_orclsp_sys"


def main() -> None:
    conn = _connect_saved_oracle(CONNECTION)
    try:
        cur = conn.cursor()
        cur.execute(
            "select instance_name, host_name, version, "
            "to_char(sysdate,'YYYY-MM-DD HH24:MI:SS') "
            "from v$instance"
        )
        print("INSTANCE", cur.fetchone())

        cur.execute(
            "select count(*), min(sample_time), max(sample_time) "
            "from v$active_session_history"
        )
        print("ASH_BUFFER", cur.fetchone())
        cur.execute(
            "select name, value from v$parameter "
            "where name in ('statistics_level','control_management_pack_access')"
        )
        print("PARAMS", cur.fetchall())
        cur.execute(
            "select status, count(*) from v$session "
            "where type = 'USER' group by status order by 1"
        )
        print("USER_SESSIONS", cur.fetchall())
        cur.execute(
            "select sid, serial#, username, status, event, wait_class, sql_id, "
            "seconds_in_wait from v$session "
            "where type = 'USER' and status = 'ACTIVE' "
            "order by seconds_in_wait desc fetch first 20 rows only"
        )
        print("--- ACTIVE USER SESSIONS ---")
        for row in cur:
            print(row)
        cur.execute(
            "select count(*) from v$active_session_history "
            "where sample_time >= systimestamp - interval '15' minute"
        )
        print("ASH_SAMPLES_15M", cur.fetchone()[0])

        print("--- WAIT CLASS / EVENT ---")
        cur.execute(
            """
            select nvl(wait_class,'ON CPU') wait_class,
                   nvl(event,'ON CPU') event,
                   count(*) samples,
                   count(distinct session_id) sessions,
                   round(count(*)/15,1) aas
            from v$active_session_history
            where sample_time >= systimestamp - interval '15' minute
            group by nvl(wait_class,'ON CPU'), nvl(event,'ON CPU')
            order by samples desc
            fetch first 20 rows only
            """
        )
        for row in cur:
            print(row)

        print("--- TOP SQL ---")
        cur.execute(
            """
            select nvl(sql_id,'(none)') sql_id,
                   nvl(session_state,'UNKNOWN') session_state,
                   nvl(event,'ON CPU') event,
                   count(*) samples,
                   count(distinct session_id||':'||session_serial#) sessions
            from v$active_session_history
            where sample_time >= systimestamp - interval '15' minute
            group by nvl(sql_id,'(none)'),
                     nvl(session_state,'UNKNOWN'),
                     nvl(event,'ON CPU')
            order by samples desc
            fetch first 25 rows only
            """
        )
        for row in cur:
            print(row)
        cur.close()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
