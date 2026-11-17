# Spain sync reconciliation — 2026-11-17

## PH RF collision repaired

The Spain target had a stale global row for serial `6600000000047` carrying RF `0226055B0043402E`. Current PH staging assigned that RF to serial `6600000000147`, and the old serial was absent from every current site staging view.

The repair retained the older target serial and its 2020-12-15 dates, cleared its RF, inserted the current PH staging row for serial `6600000000147` with the matching RF, and added one `PH` / `T` transfer log entry. A post-commit read confirmed both target rows and the transfer log entry.

## Backlog diagnostic correction

The prior backlog comparison treated `NULL` RF values as unequal because SQL `NULL = NULL` is unknown. `site_backlog.py` now compares RFs null-safely, so rows with the same serial and both RF values null count as matching.

Post-repair live counts using that comparison:

| Site | Staging | Eligible | Serial mismatch | RF conflict | Completed | Ledger mismatch |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Hungary | 997 | 0 | 0 | 0 | 997 | 0 |
| PH | 246 | 0 | 0 | 0 | 246 | 0 |
| RH | 41 | 0 | 0 | 0 | 41 | 0 |

Ofakim returned no staging rows in this aggregate query.
