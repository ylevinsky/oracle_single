"""Read-only RAG indexing and session diagnostics."""

def inspect(database):
    with database.cursor() as cursor:
        cursor.execute("SELECT count(*), max(indexed_at)::text FROM rag_documents")
        count, latest = cursor.fetchone()
        cursor.execute("""SELECT pid, state, wait_event_type, wait_event,
                          pg_blocking_pids(pid), application_name
                          FROM pg_stat_activity WHERE datname=current_database()
                          AND pid <> pg_backend_pid()""")
        sessions = [dict(zip([column[0] for column in cursor.description], row))
                    for row in cursor.fetchall()]
    return {"documents": count, "latest_indexed_at": latest, "sessions": sessions}
