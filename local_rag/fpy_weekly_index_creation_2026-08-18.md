# FLEX index creation: FPY_WEEKLY access path

- Request and scope: create only the proposed index for the FLEX / `SYSTEM_ATE_2.UUT_RESULT` FPY_WEEKLY workload; no DML, drops, or statement rewrites.
- Plan evidence: the generic schema plan collector searched 30 days of retained `V$SQL` cursors in `EREPORTS` for `YIELD_SUM_REPORT`, `SYSTEM_ATE_2_UUT_RESULT`, and `SYSTEM_ATE_2_STEP_RESULT`; no matching cursors were retained.
- Index created: `CREATE INDEX SYSTEM_ATE_2.IX_UUT_RESULT_SERIAL_START ON SYSTEM_ATE_2.UUT_RESULT (UUT_SERIAL_NUMBER, START_DATE_TIME)`.
- Outcome: the repository Oracle MCP returned `status: created` on 2026-08-18.
- Safety: no DELETE, INSERT, UPDATE, DROP, replacement, or SQL-rewrite action was issued.
- Handled implementation error: the first local source patch was rejected before changes with `invalid patch: multiple operations target C:\\git\\ORCL\\oracle_connectivity_mcp\\server.py`; it was corrected by applying one unified-file patch.
- MCP feature: added the confirmation-gated `create_saved_oracle_index` operation. It permits only simple identifiers, a single normal index, and blocks identical existing definitions.