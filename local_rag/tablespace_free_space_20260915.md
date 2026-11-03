# Tablespace free-space expansion

- Recorded: 2026-09-15
- User request: increase all tablespaces to have at least 10% free space.
- Target scope: all saved Oracle targets reachable through the repository-scoped `myoracle` MCP server.
- Verified baseline: six reachable targets had tablespaces below 10%; the saved `DWH` target could not be inspected because the Oracle connection timed out.
- Exact handled error (sanitized): `OperationalError: DPY-6005: cannot connect to database; timed out` for saved target `DWH`.
- Verified solution: added one non-autoextending 1 GiB datafile through the `expand_saved_tablespace` MCP tool to each below-threshold tablespace: `DWH_CL.SYSTEM`, `FLEX.USERS`, `PH.SYSTEM`, `RH.SYSTEM`, `es_db2_orclsp_sys.SYSTEM`, and `es_db2_orclsp_sys.USERS`. A post-change `inspect_all_saved_database_space` check confirmed every inspected tablespace is at least 10% free.
- Current blocker: `DWH` remains unverified and unchanged until its saved Oracle endpoint is reachable.
- Handled ingestion errors: the first RAG-ingest attempt supplied a path outside the MCP repository root; the tool rejected it. A retry through the MCP tool exceeded its subprocess timeout while the local embedding model was loading. The maintained local RAG CLI was then run directly as the documented fallback after the MCP attempt, and indexed this record successfully as two chunks.
- MCP/code changes: no MCP code change; used existing `inspect_all_saved_database_space`, `expand_saved_tablespace`, and `inspect_local_rag_database` tools, with the documented local RAG CLI fallback for ingestion.
- Secrets: no credentials, passwords, tokens, or private connection details are stored in this record.
