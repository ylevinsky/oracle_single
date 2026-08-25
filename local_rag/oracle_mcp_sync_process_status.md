# Oracle MCP Sync Process Status Tool

- Date: 2026-08-18
- User request: inspect `C:\git\ORCL\refresh_mv.py` and implement a local Oracle MCP tool to check synchronization-process status; update local RAG and repository rules.
- Target scope: saved Oracle connections running the `TRANSFER_USER` materialized-view synchronization workflow, with Repair Center as the primary target.
- Prior diagnostic gap: the gateway exposed separate materialized-view activity and wait checks, but no single status tool correlated the actual `refresh_mv.py` worker identity, workflow audit records, and current materialized-view metadata. A stale Codex tool declaration also did not expose existing materialized-view diagnostics even though the server source registered them.
- Feature created: `inspect_saved_sync_process_status(connection_name)` in `C:\git\ORCL\oracle_connectivity_mcp\server.py`.
- Read-only evidence returned by the tool: `DAILY_TRANSFER_PY` worker sessions, matching `V$SESSION_LONGOPS` work, `TRANSFER_USER.LOG_PROCEDURE` records for `DAILY_TRANSFER` from a trailing date window, and `TRANSFER_USER` rows from `DBA_MVIEWS`.
- Status rule: active worker sessions mean `running`; otherwise the latest audit state `End` means `completed`, `Error` means `failed`, and no usable evidence means `unknown`.
- Rules and documentation update: `C:\git\ORCL\AGENTS.md` now requires this tool for refresh status and rejects inference of the newer `REFRESH_MV:<run-id>` workflow; `refresh_mv.md` now documents the behavior implemented by the inspected source.
- RAG indexing history: `rag.py ingest` previously timed out while PostgreSQL was unavailable. PostgreSQL was restored and the compact status record was indexed; this detailed source is re-indexed after this update.
- Verified live status: a fresh repository Oracle MCP gateway ran the tool against Repair Center on 2026-08-18. It returned `completed`, with no active `DAILY_TRANSFER_PY` workers and no matching long operations. The latest 2026-08-17 run started at 23:00:02 and wrote `End` outcomes for RH at 23:02:48, Hungary at 23:11:36, and Ofakim at 23:30:19. The reported materialized views were valid.
- Verification status: verified read-only against the saved Repair Center target. The current Codex session may still need restart before its static tool declaration lists the new tool.
- Query correction: audit history is limited by `PROC_START >= SYSTIMESTAMP - NUMTODSINTERVAL(:history_days, 'DAY')`, with `history_days=7` by default and a supported range of 1 through 90. It no longer uses a `ROWNUM` cap.
