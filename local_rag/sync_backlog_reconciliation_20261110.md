# Sync backlog reconciliation status — 2026-11-10

- Request: Check the live Spain Repair Center sync process and fix its reported backlog.
- Target: Saved Oracle connection `es_db2_orclsp_sys`; status queried with the local myoracle MCP. No production data was changed.
- Live process: Completed, no active workers or long operations. Latest successful site outcomes were recorded 2026-11-09 22:01-22:11 (database local time).
- Live staging reconciliation: Ofakim 0 rows; Hungary 1,217; RH 318; PH 435. Eligible inserts are 0 for all sites. Matching global serial/RF and transfer-ledger rows: Hungary 1,214, RH 317, PH 433. Ledgered serial/RF mismatches: Hungary 3, RH 1, PH 1. PH has one RF conflict. These rows are not eligible for an insert-only backlog repair.
- Root cause of false backlog counts: the status query counted all serial matches as blocked without checking whether the same serial/RF was already present and logged as transferred.
- Change: `myoracle_mcp/site_backlog.py` now identifies completed same-key logged transfers, true ledger mismatches, and RF conflicts separately. The package was restarted and the live diagnostic verified these counts.
- Remaining action: investigate the five ledger mismatches and one PH RF conflict before changing production records; current evidence does not establish which source or destination values should win.
- Recent transient errors: site refreshes recorded ORA-12008 / ORA-01555, followed by same-run successful retries. They did not leave an active worker or eligible staging backlog.
